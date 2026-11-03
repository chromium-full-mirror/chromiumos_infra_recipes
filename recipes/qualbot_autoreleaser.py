# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to manage Qualbot (chromeos/infra/fw_qual_automation) releases via CIPD.

This recipe automates the release lifecycle across staging and production:
- STAGE_STAGING (staging-qualbot-autoreleaser): Periodically clones
  refs/heads/main and uploads a CIPD package tagged with git_revision and
  pointed to by the 'staging' CIPD ref.
- STAGE_PROD (qualbot-autoreleaser): Promotes the 'staging' CIPD ref instance
  to the 'prod' CIPD ref once staging qualification gates are satisfied,
  evaluating the newest daily canary run (user_request_id) per
  (board, model, test_plan) target so a clean next-day canary rerun on the
  same staging SHA clears an earlier transient lab failure.
- Ad-hoc / Rollbacks: Allows operators to re-point the 'prod' CIPD ref to any
  previous CIPD instance ID or git_revision:<sha> tag.
"""

from google.protobuf import timestamp_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as bb_builder_common
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.qualbot_autoreleaser import QualbotAutoreleaserProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    "recipe_engine/buildbucket",
    "recipe_engine/cipd",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/json",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "git",
]

PROPERTIES = QualbotAutoreleaserProperties

FW_QUAL_REPO_URL = (
    "https://chrome-internal.googlesource.com/chromeos/infra/fw_qual_automation"
)
DEFAULT_CIPD_PACKAGE = "chromiumos/infra/cros_test_runner/fw_qual_automation"
STAGING_GATE_BUILDERS = (
    "staging-qualbot-pipeline",
    "staging-qualbot-pipeline-e2e",
)
BIGQUERY_PROJECT = "firmware-bigquery"
_HEX_CHARS = frozenset("0123456789abcdef")


def RunSteps(api: RecipeApi, properties: QualbotAutoreleaserProperties):
  stage = properties.stage or QualbotAutoreleaserProperties.STAGE_STAGING
  dry_run = bool(properties.dry_run)

  if stage == QualbotAutoreleaserProperties.STAGE_PROD:
    _promote_prod(api, properties, dry_run=dry_run)
  else:
    _uprev_staging(api, properties, dry_run=dry_run)


def _uprev_staging(
    api: RecipeApi,
    properties: QualbotAutoreleaserProperties,
    dry_run: bool = False,
):
  source_ref = properties.source_ref or "refs/heads/main"
  target_ref = properties.target_ref or "staging"

  repo_dir = api.path.start_dir.joinpath("fw_qual_automation")
  api.git.clone(FW_QUAL_REPO_URL, target_path=repo_dir)

  with api.context(cwd=repo_dir):
    with api.step.nest("uprev staging cipd ref"):
      commit_sha = api.git.fetch_ref("origin", source_ref)

      if not dry_run:
        pkg_dir = api.path.mkdtemp(prefix="qualbot_cipd")
        rev_file = pkg_dir.joinpath("git_revision")
        api.file.write_text("write git_revision", rev_file, commit_sha)
        pkg_def = api.cipd.PackageDefinition(
            package_name=DEFAULT_CIPD_PACKAGE,
            package_root=pkg_dir,
            install_mode="copy",
        )
        pkg_def.add_file(rev_file)
        api.cipd.create_from_pkg(
            pkg_def=pkg_def,
            refs=[target_ref],
            tags={"git_revision": commit_sha},
        )


def _promote_prod(
    api: RecipeApi,
    properties: QualbotAutoreleaserProperties,
    dry_run: bool = False,
):
  source_ref = properties.source_ref or "staging"
  target_ref = properties.target_ref or "prod"

  with api.step.nest("promote prod cipd ref") as pres:
    # Look up the CIPD package instance currently pointed to by source_ref.
    desc = api.cipd.describe(
        package_name=DEFAULT_CIPD_PACKAGE,
        version=source_ref,
    )

    if not properties.force and any(r.ref == target_ref for r in desc.refs):
      pres.step_text = (f"{target_ref} already points to {source_ref} "
                        f"({desc.pin.instance_id}); skipping")
      return

    if not properties.force:
      # Compute soak window start: since source_ref was last updated, capped to
      # the last 24 hours.
      now_ts = api.buildbucket.build.create_time.ToSeconds()
      ref_ts = next(
          (r.modified_ts for r in desc.refs if r.ref == source_ref),
          desc.registered_ts,
      )
      start_ts = max(ref_ts, now_ts - 24 * 60 * 60)

      log_lines = [
          f"source_ref: {source_ref} (instance_id={desc.pin.instance_id})",
          f"ref_ts: {ref_ts}, now_ts: {now_ts}, soak_start_ts: {start_ts}",
      ]
      try:
        missing_builders = []
        failed_builds_by_builder = {}

        # Query completed scheduled staging pipeline runs in the soak window for
        # each required staging builder, excluding ad-hoc or CL tryjob runs via
        # user_agent:luci-scheduler.
        for builder_name in STAGING_GATE_BUILDERS:
          builds = api.buildbucket.search(
              predicate=bb_service.BuildPredicate(
                  builder=bb_builder_common.BuilderID(
                      project="chromeos",
                      bucket="staging",
                      builder=builder_name,
                  ),
                  create_time=bb_common.TimeRange(
                      start_time=timestamp_pb2.Timestamp(seconds=start_ts),
                  ),
                  status=bb_common.ENDED_MASK,
                  tags=[
                      bb_common.StringPair(
                          key="user_agent",
                          value="luci-scheduler",
                      ),
                  ],
              ),
              step_name=f"search {builder_name} builds",
          )
          log_lines.append(f"considered {builder_name} builds ({len(builds)}):")
          for b in builds:
            status_name = bb_common.Status.Name(b.status)
            log_lines.append(f"  - build {b.id}: {status_name} "
                             f"(https://ci.chromium.org/b/{b.id})")
            pres.links[f"{builder_name} {b.id} ({status_name})"] = (
                f"https://ci.chromium.org/b/{b.id}")
          if not builds:
            missing_builders.append(builder_name)
          failed = [b for b in builds if b.status != bb_common.SUCCESS]
          if failed:
            failed_builds_by_builder[builder_name] = failed

        # Require at least one completed staging soak run per builder and that
        # all succeeded.
        if missing_builders:
          missing_str = ", ".join(missing_builders)
          raise api.step.StepFailure(
              f"No completed builds found for [{missing_str}] since "
              "staging ref update.")
        if failed_builds_by_builder:
          details = "; ".join(
              f"{b_name} ({', '.join(str(b.id) for b in failed)})"
              for b_name, failed in failed_builds_by_builder.items())
          raise api.step.StepFailure(
              f"Staging health gate failed: non-passing builds for {details}.")

        # Verify that all configured staging canary test efforts for the
        # candidate git_revision completed and passed in BigQuery.
        commit_sha = next(
            (t.tag.split(":", 1)[1].lower()
             for t in desc.tags
             if t.tag.startswith("git_revision:")),
            None,
        )
        if (not commit_sha or not (12 <= len(commit_sha) <= 40) or
            not all(c in _HEX_CHARS for c in commit_sha)):
          raise api.step.StepFailure(
              "Missing or invalid git_revision tag on CIPD package "
              f"{DEFAULT_CIPD_PACKAGE}@{source_ref}")
        short_sha = commit_sha[:12]
        log_lines.append(f"staging git_revision: {commit_sha} ({short_sha})")

        repo_dir = api.path.start_dir.joinpath("fw_qual_automation")
        api.git.clone(FW_QUAL_REPO_URL, target_path=repo_dir)
        with api.context(cwd=repo_dir):
          api.git.checkout(commit_sha, force=True)

        targets_step = api.step(
            "list expected staging canary targets",
            [
                "vpython3",
                "-vpython-spec",
                repo_dir.joinpath(".vpython3"),
                api.resource("list_canary_targets.py"),
                repo_dir,
            ],
            stdout=api.json.output(),
            infra_step=True,
        )
        expected_targets = [(t["board"], t["model"], t["test_plan"])
                            for t in (targets_step.stdout or [])]
        if not expected_targets:
          raise api.step.StepFailure(
              "Staging canary gate failed: no canary targets configured in "
              f"builder_configs/staging/*.txtpb at {short_sha}.")

        sql = (
            "SELECT id, board, model, test_plan, test_effort_name, "
            "overall_result, CAST(testing_complete AS STRING) AS "
            "testing_complete, lifecycle_state, scheduler_state, "
            "ARRAY_TO_STRING(next_test_plans, ',') AS next_test_plans, "
            "CAST(IFNULL(action_required_test_count, 0) AS STRING) AS "
            "action_required_test_count, "
            "IFNULL(diagnostic_state, '') AS diagnostic_state, user_request_id "
            f"FROM `{BIGQUERY_PROJECT}.auto_qual_staging.test_effort_summary` "
            "WHERE REGEXP_CONTAINS(user_request_id, "
            r"CONCAT(r'^staging-canary-\d{4}-\d{2}-\d{2}-', @short_sha, "
            r"r'[0-9a-f]*$')) "
            "QUALIFY DENSE_RANK() OVER ("
            "PARTITION BY board, model, test_plan "
            "ORDER BY user_request_id DESC) = 1 "
            "ORDER BY board, model, test_plan, request_date DESC, id DESC")
        bq_step = api.step(
            "query staging canary results",
            [
                "vpython3",
                "-vpython-spec",
                repo_dir.joinpath(".vpython3"),
                api.resource("query_bq.py"),
                "--project",
                BIGQUERY_PROJECT,
                "--param",
                f"short_sha={short_sha}",
                "--sql",
                sql,
            ],
            stdout=api.json.output(),
            infra_step=True,
        )
        rows = bq_step.stdout or []

        all_targets = list(expected_targets)
        raw_rows_by_target = {}
        for row in rows:
          board = row.get("board") or ""
          model = row.get("model") or ""
          test_plan = row.get("test_plan") or ""
          key = (board, model, test_plan)
          raw_rows_by_target.setdefault(key, []).append(row)
          if key not in all_targets:
            all_targets.append(key)

        # Evaluate only the newest user_request_id (latest day) per target, and
        # require any follow-on stage to match at least its parent stage's
        # user_request_id so a prior day's stage-2 pass cannot satisfy an
        # in-flight next-day multi-stage run.
        rows_by_target = {}
        min_req_id_by_target = {}
        for key, target_rows in raw_rows_by_target.items():
          latest_req_id = max(
              (r.get("user_request_id") or "") for r in target_rows)
          latest_rows = [
              r for r in target_rows
              if (r.get("user_request_id") or "") == latest_req_id
          ]
          rows_by_target[key] = latest_rows
          board, model, _ = key
          for row in latest_rows:
            for next_plan in (row.get("next_test_plans") or "").split(","):
              if next_plan:
                next_key = (board, model, next_plan)
                if next_key not in all_targets:
                  all_targets.append(next_key)
                min_req_id_by_target[next_key] = max(
                    min_req_id_by_target.get(next_key, ""), latest_req_id)

        log_lines.append(f"staging canary targets ({len(all_targets)}), "
                         f"BigQuery rows ({len(rows)}):")
        missing_canaries = []
        failed_canaries = []
        for board, model, test_plan in all_targets:
          target_label = f"{board}/{model} ({test_plan})"
          key = (board, model, test_plan)
          min_req_id = min_req_id_by_target.get(key, "")
          target_rows = [
              r for r in rows_by_target.get(key, [])
              if (r.get("user_request_id") or "") >= min_req_id
          ]
          if not target_rows:
            log_lines.append(f"  - {target_label}: MISSING")
            missing_canaries.append(target_label)
            continue

          has_terminal_pass = False
          failed_row_details = []
          for row in target_rows:
            overall_result = row.get("overall_result") or ""
            testing_complete = (
                str(row.get("testing_complete")).lower() == "true")
            lifecycle_state = row.get("lifecycle_state") or ""
            scheduler_state = row.get("scheduler_state") or ""
            diagnostic_state = row.get("diagnostic_state") or ""
            action_required = int(row.get("action_required_test_count") or 0)
            effort_name = row.get("test_effort_name")
            log_lines.append(f"  - {target_label}: {effort_name} "
                             f"(overall_result={overall_result}, "
                             f"testing_complete={testing_complete}, "
                             f"lifecycle_state={lifecycle_state}, "
                             f"scheduler_state={scheduler_state}, "
                             f"diagnostic_state={diagnostic_state}, "
                             f"action_required_test_count={action_required})")
            # Require strict overall_result == "PASS" on completed canary rows:
            # waived test failures already roll up to "PASS" in
            # TestStatusAnalyzer, whereas "TEST_NA" means zero required boot
            # tests executed (and "WARN" is not an effort-level terminal pass).
            is_failed_row = (
                overall_result in ("FAIL", "TIMED_OUT") or
                lifecycle_state in ("ACTION_REQUIRED", "CANCELLED") or
                action_required > 0 or
                diagnostic_state not in ("", "NOT_APPLICABLE") or
                (testing_complete and overall_result != "PASS"))
            if is_failed_row:
              failed_row_details.append(
                  f"{target_label} [overall_result={overall_result}, "
                  f"lifecycle_state={lifecycle_state}, "
                  f"diagnostic_state={diagnostic_state}]")
            elif (testing_complete and overall_result == "PASS" and
                  ((lifecycle_state == "COMPLETE" and scheduler_state
                    == "COMPLETE") or lifecycle_state == "FOLLOW_ON_STAGE")):
              has_terminal_pass = True

          if failed_row_details:
            failed_canaries.append(failed_row_details[0])
          elif not has_terminal_pass:
            r0 = target_rows[0]
            failed_canaries.append(
                f"{target_label} [overall_result={r0.get('overall_result')}, "
                f"lifecycle_state={r0.get('lifecycle_state')}, "
                f"scheduler_state={r0.get('scheduler_state')}]")

        canary_errors = []
        if missing_canaries:
          canary_errors.append(
              f"missing canary test efforts: {', '.join(missing_canaries)}")
        if failed_canaries:
          canary_errors.append(
              f"non-passing canary test efforts: {'; '.join(failed_canaries)}")
        if canary_errors:
          raise api.step.StepFailure(
              f"Staging canary gate failed for git_revision {short_sha}: "
              f"{' | '.join(canary_errors)}.")
      finally:
        pres.logs["soak gate summary"] = log_lines

    # Point target_ref ('prod') to the verified staging CIPD instance.
    if not dry_run:
      api.cipd.set_ref(
          package_name=DEFAULT_CIPD_PACKAGE,
          version=desc.pin.instance_id,
          refs=[target_ref],
      )


def GenTests(api: RecipeTestApi):
  valid_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
  staging_cipd_describe = api.step_data(
      f"promote prod cipd ref.cipd describe {DEFAULT_CIPD_PACKAGE}",
      api.cipd.example_describe(
          package_name=DEFAULT_CIPD_PACKAGE,
          version="staging",
          test_data_refs=["staging"],
          test_data_tags=[f"git_revision:{valid_sha}"],
      ),
  )
  expected_canary_targets = [
      {
          "board": "nissa",
          "model": "domiso",
          "test_plan": "cros/boot"
      },
      {
          "board": "fatcat",
          "model": "moonstone",
          "test_plan": "al/boot"
      },
      {
          "board": "fatcat",
          "model": "lapis",
          "test_plan": "al/boot-direct"
      },
      {
          "board": "fatcat",
          "model": "lapis",
          "test_plan": "al/boot"
      },
  ]
  passing_canary_results = [
      # Includes a newly-spawned in-flight 2nd cycle row alongside a completed
      # PASS row to verify same-day 22h re-runs do not falsely fail the gate.
      {
          "board": "nissa",
          "model": "domiso",
          "test_plan": "cros/boot",
          "test_effort_name": "nissa-domiso-cros/boot-cycle2",
          "overall_result": "NO_RESULTS",
          "testing_complete": "false",
          "lifecycle_state": "QUEUED_OR_RATE_LIMITED",
          "scheduler_state": "RATE_LIMITED",
          "next_test_plans": "",
          "action_required_test_count": "0",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
      },
      {
          "board": "nissa",
          "model": "domiso",
          "test_plan": "cros/boot",
          "test_effort_name": "nissa-domiso-cros/boot-cycle1",
          "overall_result": "PASS",
          "testing_complete": "true",
          "lifecycle_state": "COMPLETE",
          "scheduler_state": "COMPLETE",
          "next_test_plans": "",
          "action_required_test_count": "0",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
      },
      # Prior-day transient FAIL superseded by a clean next-day PASS on the
      # same staging SHA.
      {
          "board": "fatcat",
          "model": "moonstone",
          "test_plan": "al/boot",
          "test_effort_name": "fatcat-moonstone-al/boot-day2",
          "overall_result": "PASS",
          "testing_complete": "true",
          "lifecycle_state": "COMPLETE",
          "scheduler_state": "COMPLETE",
          "next_test_plans": "",
          "action_required_test_count": "0",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
      },
      {
          "board": "fatcat",
          "model": "moonstone",
          "test_plan": "al/boot",
          "test_effort_name": "fatcat-moonstone-al/boot-day1",
          "overall_result": "FAIL",
          "testing_complete": "true",
          "lifecycle_state": "ACTION_REQUIRED",
          "scheduler_state": "AWAITING_TRIAGE",
          "next_test_plans": "",
          "action_required_test_count": "1",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-04-a1b2c3d4e5f6",
      },
      # Multi-stage effort: Stage 1 ends in FOLLOW_ON_STAGE / AWAITING_SCHEDULER
      # and promotes Stage 2 (al/boot) which ends in COMPLETE / COMPLETE.
      {
          "board": "fatcat",
          "model": "lapis",
          "test_plan": "al/boot-direct",
          "test_effort_name": "fatcat-lapis-al/boot-direct",
          "overall_result": "PASS",
          "testing_complete": "true",
          "lifecycle_state": "FOLLOW_ON_STAGE",
          "scheduler_state": "AWAITING_SCHEDULER",
          "next_test_plans": "al/boot",
          "action_required_test_count": "0",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
      },
      {
          "board": "fatcat",
          "model": "lapis",
          "test_plan": "al/boot",
          "test_effort_name": "fatcat-lapis-al/boot",
          "overall_result": "PASS",
          "testing_complete": "true",
          "lifecycle_state": "COMPLETE",
          "scheduler_state": "COMPLETE",
          "next_test_plans": "",
          "action_required_test_count": "0",
          "diagnostic_state": "NOT_APPLICABLE",
          "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
      },
  ]

  yield api.test(
      "default_uprev_staging",
      api.post_check(
          post_process.StepCommandContains,
          "git clone",
          [FW_QUAL_REPO_URL],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "uprev staging cipd ref.git fetch",
          ["origin", "refs/heads/main:"],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "uprev staging cipd ref.create chromiumos/infra/cros_test_runner/fw_qual_automation",
          [
              "-ref",
              "staging",
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "promote_prod_already_at_staging",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      api.step_data(
          f"promote prod cipd ref.cipd describe {DEFAULT_CIPD_PACKAGE}",
          api.cipd.example_describe(
              package_name=DEFAULT_CIPD_PACKAGE,
              version="staging",
              test_data_refs=["staging", "prod"],
              test_data_tags=[f"git_revision:{valid_sha}"],
          ),
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "promote_prod_dry_run",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
              dry_run=True,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.step_data(
          "promote prod cipd ref.list expected staging canary targets",
          stdout=api.json.output(expected_canary_targets),
      ),
      api.step_data(
          "promote prod cipd ref.query staging canary results",
          stdout=api.json.output(passing_canary_results),
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd describe chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-version", "staging"],
      ),
      api.post_check(
          post_process.MustRun,
          "promote prod cipd ref.query staging canary results",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "promote_prod",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.step_data(
          "promote prod cipd ref.list expected staging canary targets",
          stdout=api.json.output(expected_canary_targets),
      ),
      api.step_data(
          "promote prod cipd ref.query staging canary results",
          stdout=api.json.output(passing_canary_results),
      ),
      api.post_check(
          post_process.MustRun,
          "promote prod cipd ref.query staging canary results",
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-ref", "prod"],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "promote_prod_no_builds",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "promote_prod_failed_staging_build",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [
              api.buildbucket.ci_build_message(status="SUCCESS"),
              api.buildbucket.ci_build_message(status="FAILURE"),
          ],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "promote_prod_missing_git_revision_tag",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      api.step_data(
          f"promote prod cipd ref.cipd describe {DEFAULT_CIPD_PACKAGE}",
          api.cipd.example_describe(
              package_name=DEFAULT_CIPD_PACKAGE,
              version="staging",
              test_data_refs=["staging"],
              test_data_tags=[],
          ),
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          "Missing or invalid git_revision tag on CIPD package",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "promote_prod_no_configured_canary_targets",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.step_data(
          "promote prod cipd ref.list expected staging canary targets",
          stdout=api.json.output([]),
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          "no canary targets configured",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "promote_prod_missing_and_failed_canary_efforts",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
          )),
      staging_cipd_describe,
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.step_data(
          "promote prod cipd ref.list expected staging canary targets",
          stdout=api.json.output(expected_canary_targets),
      ),
      api.step_data(
          "promote prod cipd ref.query staging canary results",
          stdout=api.json.output([
              # Parent effort diagnosing a failure alongside a passing
              # diagnostic child: must still fail the gate.
              {
                  "board": "nissa",
                  "model": "domiso",
                  "test_plan": "cros/boot",
                  "test_effort_name": "nissa-domiso-cros/boot-diag",
                  "overall_result": "PASS",
                  "testing_complete": "true",
                  "lifecycle_state": "COMPLETE",
                  "scheduler_state": "COMPLETE",
                  "next_test_plans": "",
                  "action_required_test_count": "0",
                  "diagnostic_state": "NOT_APPLICABLE",
              },
              {
                  "board": "nissa",
                  "model": "domiso",
                  "test_plan": "cros/boot",
                  "test_effort_name": "nissa-domiso-cros/boot-parent",
                  "overall_result": "FAIL",
                  "testing_complete": "false",
                  "lifecycle_state": "ACTION_REQUIRED",
                  "scheduler_state": "AWAITING_TRIAGE",
                  "next_test_plans": "",
                  "action_required_test_count": "1",
                  "diagnostic_state": "DIAGNOSING_IN_FLIGHT",
              },
              # Still SCHEDULED on day 2; stale day-1 follow-on row must not
              # satisfy day 2's follow-on stage.
              {
                  "board": "fatcat",
                  "model": "lapis",
                  "test_plan": "al/boot-direct",
                  "test_effort_name": "fatcat-lapis-al/boot-direct-day2",
                  "overall_result": "UNKNOWN",
                  "testing_complete": None,
                  "lifecycle_state": None,
                  "scheduler_state": "SCHEDULED",
                  "next_test_plans": "al/boot,al/security",
                  "action_required_test_count": "0",
                  "diagnostic_state": "",
                  "user_request_id": "staging-canary-2026-11-05-a1b2c3d4e5f6",
              },
              {
                  "board": "fatcat",
                  "model": "lapis",
                  "test_plan": "al/boot",
                  "test_effort_name": "fatcat-lapis-al/boot-day1",
                  "overall_result": "PASS",
                  "testing_complete": "true",
                  "lifecycle_state": "COMPLETE",
                  "scheduler_state": "COMPLETE",
                  "next_test_plans": "",
                  "action_required_test_count": "0",
                  "diagnostic_state": "NOT_APPLICABLE",
                  "user_request_id": "staging-canary-2026-11-04-a1b2c3d4e5f6",
              },
              # Extra unexpected row also evaluated.
              {
                  "board": "dedede",
                  "model": "drawman",
                  "test_plan": "cros/boot",
                  "test_effort_name": "dedede-drawman-cros/boot",
                  "overall_result": "PASS",
                  "testing_complete": "true",
                  "lifecycle_state": "CANCELLED",
                  "scheduler_state": "AWAITING_SCHEDULER",
                  "next_test_plans": "",
                  "action_required_test_count": "0",
                  "diagnostic_state": "NOT_APPLICABLE",
              },
          ]),
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          "missing canary test efforts.*non-passing canary test efforts",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "promote_prod_force",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
              force=True,
          )),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.search staging-qualbot-pipeline builds",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.search staging-qualbot-pipeline-e2e builds",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "promote prod cipd ref.query staging canary results",
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-ref", "prod"],
      ),
      api.post_process(post_process.DropExpectation),
  )
