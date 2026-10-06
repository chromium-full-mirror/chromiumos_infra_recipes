# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to manage Qualbot (chromeos/infra/fw_qual_automation) releases via CIPD.

This recipe automates the release lifecycle across staging and production:
- STAGE_STAGING (staging-qualbot-autoreleaser): Periodically clones
  refs/heads/main and uploads a CIPD package tagged with git_revision and
  pointed to by the 'staging' CIPD ref.
- STAGE_PROD (qualbot-autoreleaser): Promotes the 'staging' CIPD ref instance
  to the 'prod' CIPD ref once staging qualification gates are satisfied.
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
    desc = api.cipd.describe(package_name=DEFAULT_CIPD_PACKAGE,
                             version=source_ref)

    if not properties.force:
      # Compute soak window start: since source_ref was last updated, capped to
      # the last 24 hours.
      now_ts = api.buildbucket.build.create_time.ToSeconds()
      ref_ts = next(
          (r.modified_ts for r in desc.refs if r.ref == source_ref),
          desc.registered_ts,
      )
      start_ts = max(ref_ts, now_ts - 24 * 60 * 60)

      # Query completed scheduled staging pipeline runs in the soak window,
      # excluding ad-hoc or CL tryjob runs via user_agent:luci-scheduler.
      builds = api.buildbucket.search(
          predicate=bb_service.BuildPredicate(
              builder=bb_builder_common.BuilderID(
                  project="chromeos",
                  bucket="staging",
                  builder="staging-qualbot-pipeline",
              ),
              create_time=bb_common.TimeRange(
                  start_time=timestamp_pb2.Timestamp(seconds=start_ts),
              ),
              status=bb_common.ENDED_MASK,
              tags=[
                  bb_common.StringPair(key="user_agent",
                                       value="luci-scheduler"),
              ],
          ))
      log_lines = [
          f"source_ref: {source_ref} (instance_id={desc.pin.instance_id})",
          f"ref_ts: {ref_ts}, now_ts: {now_ts}, soak_start_ts: {start_ts}",
          f"considered builds ({len(builds)}):",
      ]
      for b in builds:
        status_name = bb_common.Status.Name(b.status)
        log_lines.append(f"  - build {b.id}: {status_name} "
                         f"(https://ci.chromium.org/b/{b.id})")
        pres.links[f"staging build {b.id} ({status_name})"] = (
            f"https://ci.chromium.org/b/{b.id}")
      pres.logs["soak gate summary"] = log_lines

      # Require at least one completed staging soak run and that all succeeded.
      if not builds:
        raise api.step.StepFailure(
            "No completed staging-qualbot-pipeline builds found since "
            "staging ref update.")
      failed_builds = [b for b in builds if b.status != bb_common.SUCCESS]
      if failed_builds:
        failed_ids = ", ".join(str(b.id) for b in failed_builds)
        raise api.step.StepFailure(
            "Staging health gate failed: non-passing "
            f"staging-qualbot-pipeline builds ({failed_ids}).")

    # Point target_ref ('prod') to the verified staging CIPD instance.
    if not dry_run:
      api.cipd.set_ref(
          package_name=DEFAULT_CIPD_PACKAGE,
          version=desc.pin.instance_id,
          refs=[target_ref],
      )


def GenTests(api: RecipeTestApi):
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
      "promote_prod_dry_run",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
              dry_run=True,
          )),
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.buildbucket.search",
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd describe chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-version", "staging"],
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
      api.buildbucket.simulated_search_results(
          [api.buildbucket.ci_build_message(status="SUCCESS")],
          step_name="promote prod cipd ref.buildbucket.search",
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
      api.buildbucket.simulated_search_results(
          [],
          step_name="promote prod cipd ref.buildbucket.search",
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
      api.buildbucket.simulated_search_results(
          [
              api.buildbucket.ci_build_message(status="SUCCESS"),
              api.buildbucket.ci_build_message(status="FAILURE"),
          ],
          step_name="promote prod cipd ref.buildbucket.search",
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
          "promote prod cipd ref.buildbucket.search",
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-ref", "prod"],
      ),
      api.post_process(post_process.DropExpectation),
  )
