# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget incrementally."""

from typing import Generator
from typing import Optional

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'git',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
REPO_SYNC_JOBS = 16


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  with api.build_menu.configure_builder() as config, \
    api.build_menu.setup_workspace_and_chroot():

    return DoRunSteps(api, config)


# Tests reliability of incremental build by performing two builds:
#   1. Revert the checkout back in time, build_packages for that old state,
#      generating local artifacts.
#   2. Move the checkout back to ToT. Build from that.
def DoRunSteps(api: RecipeApi, config: BuilderConfig) -> Optional[RawResult]:
  snapshot_branch_name = "snapshot"
  snapshot_delta = "7.days.ago"

  manifest_internal_tempdir = api.path.mkdtemp()
  manifest_internal_url = "https://chrome-internal.googlesource.com/chromeos/manifest-internal"
  api.git.clone(manifest_internal_url, target_path=manifest_internal_tempdir,
                depth=1)

  # Get old snapshot hash.
  delta_hash_result = api.step(f"Get {snapshot_delta} manifest snapshot", [
      "git", "-C", manifest_internal_tempdir, "rev-list", "-1", "--before",
      snapshot_delta, snapshot_branch_name
  ], stdout=api.raw_io.output_text())
  delta_hash = delta_hash_result.stdout.strip()

  # Rewind the source to old snapshot.
  api.step(f"Revert manifest to {snapshot_delta} snapshot",
           ["git", "-C", manifest_internal_tempdir, delta_hash])
  api.step(
      f"Apply {snapshot_delta} manifest snapshot",
      [
          "repo", "init", "--standalone-manifest",
          f"file://{manifest_internal_tempdir}/snapshot.xml"
      ],
  )
  api.repo.sync(jobs=REPO_SYNC_JOBS, force_sync=True, detach=True,
                retry_fetches=3, force_remove_dirty=True)

  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  failing_build_exception = None

  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      # Fast forward the source to latest snapshot.
      api.step("Revert manifest to the latest snapshot",
               ["git", "-C", manifest_internal_tempdir, snapshot_branch_name])

      api.step(
          "Apply latest manifest snapshot",
          [
              "repo", "init", "--standalone-manifest",
              f"file://{manifest_internal_tempdir}/snapshot.xml"
          ],
      )
      api.repo.sync(jobs=REPO_SYNC_JOBS, force_sync=True, detach=True,
                    retry_fetches=3, force_remove_dirty=True)

      if api.build_menu.install_packages(config, packages):
        # Only want to build and test the image once (after the ff/rebuild).
        api.build_menu.build_and_test_images(config)

  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (as stated above there is value in uploading the artifact even
    # in cases of build failure for debug purposes).
    failing_build_exception = sf

  # Always upload the artifacts, regardless of whether the above threw an
  # exception.
  try:
    api.build_menu.upload_artifacts(config)
  except StepFailure as sf:
    # If uploading artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  # Normal Build.
  yield api.build_menu.test(
      'inc-build',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.DoesNotRun, 'install packages (3)'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests (2)'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      build_target='amd64-generic',
      status='SUCCESS',
  )

  # Build with install-packages failure.
  yield api.build_menu.test(
      'inc-install-packages-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.build_menu.set_build_api_return(
          'install packages', endpoint='SysrootService/InstallPackages',
          retcode=2,
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ), build_target='amd64-generic', status='FAILURE')

  # Build with artifact bundling failure.
  yield api.build_menu.test(
      'inc-bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      build_target='amd64-generic',
      status='INFRA_FAILURE',
  )
