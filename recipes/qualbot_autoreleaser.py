# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to manage Qualbot (chromeos/infra/fw_qual_automation) releases.

This recipe automates the release lifecycle across staging and production:
- STAGE_STAGING (staging-qualbot-autoreleaser): Periodically fast-forwards
  refs/heads/release/staging to refs/heads/main so that new commits are soaked
  on staging-qualbot-pipeline.
- STAGE_PROD (qualbot-autoreleaser): Promotes refs/heads/release/staging to
  refs/heads/release/prod once staging qualification gates are satisfied.
- Ad-hoc / Rollbacks: Allows operators to force-push refs/heads/release/prod
  to any previous commit or release tag.
"""

from PB.recipes.chromeos.qualbot_autoreleaser import QualbotAutoreleaserProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    "recipe_engine/context",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "git",
]

PROPERTIES = QualbotAutoreleaserProperties

FW_QUAL_REPO_URL = (
    "https://chrome-internal.googlesource.com/chromeos/infra/fw_qual_automation"
)


def RunSteps(api: RecipeApi, properties: QualbotAutoreleaserProperties):
  stage = properties.stage or QualbotAutoreleaserProperties.STAGE_STAGING
  dry_run = bool(properties.dry_run)
  force = bool(properties.force)

  repo_dir = api.path.start_dir.joinpath("fw_qual_automation")
  api.git.clone(FW_QUAL_REPO_URL, target_path=repo_dir)

  with api.context(cwd=repo_dir):
    if stage == QualbotAutoreleaserProperties.STAGE_PROD:
      _promote_prod(api, properties, dry_run=dry_run, force=force)
    else:
      _uprev_staging(api, properties, dry_run=dry_run, force=force)


def _uprev_staging(
    api: RecipeApi,
    properties: QualbotAutoreleaserProperties,
    dry_run: bool = False,
    force: bool = False,
):
  source_ref = properties.source_ref or "refs/heads/main"
  target_ref = properties.target_ref or "refs/heads/release/staging"

  with api.step.nest("uprev staging ref"):
    api.git.fetch("origin", [source_ref])
    api.git.push(
        "origin",
        f"FETCH_HEAD:{target_ref}",
        dry_run=dry_run,
        force=force,
    )


def _promote_prod(
    api: RecipeApi,
    properties: QualbotAutoreleaserProperties,
    dry_run: bool = False,
    force: bool = False,
):
  source_ref = properties.source_ref or "refs/heads/release/staging"
  target_ref = properties.target_ref or "refs/heads/release/prod"

  with api.step.nest("promote prod ref"):
    # TODO(b/552097725): Validate that staging is healthy enough for prod roll.
    api.git.fetch("origin", [source_ref])
    api.git.push(
        "origin",
        f"FETCH_HEAD:{target_ref}",
        dry_run=dry_run,
        force=force,
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
          "uprev staging ref.git fetch",
          ["origin", "refs/heads/main"],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "uprev staging ref.git push",
          ["origin", "FETCH_HEAD:refs/heads/release/staging"],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "promote_prod_dry_run_force",
      api.properties(
          QualbotAutoreleaserProperties(
              stage=QualbotAutoreleaserProperties.STAGE_PROD,
              dry_run=True,
              force=True,
          )),
      api.post_check(
          post_process.StepCommandContains,
          "git clone",
          [FW_QUAL_REPO_URL],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod ref.git fetch",
          ["origin", "refs/heads/release/staging"],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "promote prod ref.git push",
          [
              "--dry-run", "--force", "origin",
              "FETCH_HEAD:refs/heads/release/prod"
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
