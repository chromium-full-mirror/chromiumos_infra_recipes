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

from PB.recipes.chromeos.qualbot_autoreleaser import QualbotAutoreleaserProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
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

  with api.step.nest("promote prod cipd ref"):
    # TODO(b/552097725): Validate that staging is healthy enough for prod roll.
    desc = api.cipd.describe(package_name=DEFAULT_CIPD_PACKAGE,
                             version=source_ref)

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
      api.post_check(
          post_process.StepCommandContains,
          "promote prod cipd ref.cipd set-ref chromiumos/infra/cros_test_runner/fw_qual_automation",
          ["-ref", "prod"],
      ),
      api.post_process(post_process.DropExpectation),
  )
