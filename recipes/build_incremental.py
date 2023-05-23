# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget incrementally."""

from typing import Generator
from typing import Optional

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipes.chromeos.build_incremental import IncrementalProperties
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
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_sdk',
    'git',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
REPO_SYNC_JOBS = 16

PROPERTIES = IncrementalProperties


def RunSteps(api: RecipeApi,
             properties: IncrementalProperties) -> Optional[RawResult]:
  with api.build_menu.configure_builder() as config, \
    api.build_menu.setup_workspace_and_chroot(update_chroot=False):
    return DoRunSteps(api, config, properties)


# Tests reliability of incremental build by performing two builds:
#   1. Revert the checkout back in time, build_packages for that old state,
#      generating local artifacts.
#   2. Move the checkout back to ToT. Build from that.
def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               extra_properties: IncrementalProperties) -> Optional[RawResult]:
  snapshot_branch_name = "origin/snapshot"

  build_time_delta = extra_properties.build_time_delta
  if not build_time_delta:
    raise StepFailure("build_time_delta input property is empty")

  # Disable cros clean-outdated-pkgs, if necessary.
  cop_enabled = extra_properties.cop_enabled
  if not cop_enabled:
    api.step(
        "Disable cros clean-outdated-pkgs",
        ["cros", "clean-outdated-pkgs", "--no-auto"],
    )

  manifest_internal_tempdir = api.path.mkdtemp()
  manifest_internal_url = "https://chrome-internal.googlesource.com/chromeos/manifest-internal"
  repo_path = str(api.repo.repo_path)

  api.git.clone(manifest_internal_url, target_path=manifest_internal_tempdir)

  # Get old snapshot hash.
  delta_hash_result = api.step(f"Get {build_time_delta} manifest snapshot", [
      "git", "-C", manifest_internal_tempdir, "rev-list", "-1", "--before",
      build_time_delta, snapshot_branch_name
  ], stdout=api.raw_io.output_text())
  delta_hash = delta_hash_result.stdout.strip()

  # Rewind the source to old snapshot.
  api.step(f"Revert manifest to {build_time_delta} snapshot",
           ["git", "-C", manifest_internal_tempdir, "checkout", delta_hash])
  with api.repo.m.depot_tools.on_path():
    api.step(
        f"Apply {build_time_delta} manifest snapshot",
        [
            repo_path, "init", "--standalone-manifest",
            f"file://{manifest_internal_tempdir}/snapshot.xml"
        ],
    )
  api.repo.sync(jobs=REPO_SYNC_JOBS, force_sync=True, detach=True,
                retry_fetches=3, force_remove_dirty=True)

  api.cros_sdk.update_chroot(
      toolchain_targets=[api.build_menu.build_target],
      build_source=config.build.sdk_update.compile_source)
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  failing_build_exception = None

  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      # Fast forward the source to latest snapshot.
      api.step("Revert manifest to the latest snapshot", [
          "git", "-C", manifest_internal_tempdir, "checkout",
          snapshot_branch_name
      ])
      with api.repo.m.depot_tools.on_path():
        api.step(
            "Apply latest manifest snapshot",
            [
                repo_path, "init", "--standalone-manifest",
                f"file://{manifest_internal_tempdir}/snapshot.xml"
            ],
        )
      api.repo.sync(jobs=REPO_SYNC_JOBS, force_sync=True, detach=True,
                    retry_fetches=3, force_remove_dirty=True)

      api.cros_sdk.update_chroot(
          toolchain_targets=[api.build_menu.build_target],
          build_source=config.build.sdk_update.compile_source)
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
      api.properties(
          IncrementalProperties(**{'build_time_delta': "7.days.ago"})),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun,
                     'Disable cros clean-outdated-pkgs'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'update sdk'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
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

  # Normal Build without cros clean-outdated-pkgs.
  yield api.build_menu.test(
      'inc-build-no-cop',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': "7.days.ago"})),
      api.properties(IncrementalProperties(**{'cop_enabled': False})),
      api.post_check(post_process.MustRun, 'Disable cros clean-outdated-pkgs'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'update sdk'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
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
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': "7.days.ago"})),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun, 'build images'),
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
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.properties(
          IncrementalProperties(**{'build_time_delta': "7.days.ago"})),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      build_target='amd64-generic',
      status='INFRA_FAILURE',
  )

  # Build without build_time_delta
  yield api.build_menu.test(
      'inc-no-build-time-delta-failure',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'install packages'),
      #   api.build_menu.set_build_api_return(
      #       'upload artifacts.call artifacts service', 'ArtifactsService/Get',
      #       retcode=1),
      build_target='amd64-generic',
      status='FAILURE',
  )
