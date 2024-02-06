# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for Bisector."""

from typing import Generator
from typing import Optional

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipes.chromeos.build_bisector import BuildBisectorProperties
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'bot_scaling',
    'build_menu',
    'cros_history',
    'cros_infra_config',
    'sysroot_archive',
]


PROPERTIES = BuildBisectorProperties


def RunSteps(api: RecipeApi,
             properties: BuildBisectorProperties) -> Optional[RawResult]:

  api.bot_scaling.drop_cpu_cores(min_cpus_left=4, max_drop_ratio=.75)

  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config, properties)


def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               properties: BuildBisectorProperties) -> Optional[RawResult]:
  sysroot_archive = api.sysroot_archive.find_best_archive(
      api.build_menu.build_target)
  env_info = api.build_menu.setup_sysroot_and_determine_relevance(
      sysroot_archive=sysroot_archive,
      snapshot_commit=properties.snapshot_commit
      if properties.HasField('snapshot_commit') else None)
  if env_info.pointless:
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was not relevant.')
  packages = env_info.packages

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      api.sysroot_archive.archive_sysroot_build(api.build_menu.chroot,
                                                api.build_menu.sysroot,
                                                api.build_menu.build_target)
      # Ignore upload prebuilt steps to speedup for bisector builder.
      # api.build_menu.upload_prebuilts(config)
      # api.build_menu.upload_host_prebuilts(config)
      api.build_menu.create_containers(config)
      api.build_menu.build_images(config)
      api.build_menu.publish_image_size_data(config)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

  try:
    api.build_menu.upload_artifacts(
        config, ignore_breakpad_symbol_generation_errors=failing_build_exception
        is not None)
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
  return None


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  # Normal postsubmit build.
  yield api.build_menu.test(
      'postsubmit-build',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'build images'),
      # api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      # By default, use Portage as the build orchestrator for all build steps.
      api.build_menu.assert_step_uses_portage('install packages',
                                              'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_portage('build images',
                                              'ImageService/Create'),
  )

  # Pointless postsubmit build.
  yield api.build_menu.test(
      'pointless-postsubmit-build',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ))

  # Postsubmit build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      # api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      status='FAILURE',
  )

  # Postsubmit build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'build images'),
      # api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      status='INFRA_FAILURE',
  )

  # Postsubmit build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      # api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'publish-image-size-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.build_menu.set_build_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData', retcode=1),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.call build API script',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.read output file',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )), builder='amd64-generic-postsubmit-publish-img-sizes')

  yield api.build_menu.test(
      'run-exit-install',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      # api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      builder='arm64-generic-kernel-v5_4-buildtest-postsubmit')

  # This builder has no output artifacts, and builds no images. (In the test
  # data...)
  yield api.build_menu.test(
      'no-run-tests',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      # api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      build_target='grunt',
      builder='grunt-postsubmit')

  # Build that uses Bazel for all its build steps.
  yield api.build_menu.test(
      'bazel',
      api.build_menu.assert_step_uses_bazel('install packages',
                                            'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_bazel('build images',
                                            'ImageService/Create'),
      builder_name='amd64-generic-bazel-postsubmit',
  )

  # Enable sysroot archive.
  yield api.build_menu.test(
      'save-sysroot-archive',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'elm'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-postsubmit.{cros-version}-{bbid}'
              },
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True
              },
              '$chromeos/sysroot_archive': {
                  'sysroot_enabled': {
                      'save_sysroot_archive': True,
                      'gs_bucket': 'foo',
                      'chromeos_start_version': 'R119-15622.0.0-88130',
                      'chromeos_end_version': 'R119-15623.0.0',
                      'chromeos_cl_diff_counts': 310
                  }
              }
          }),
      api.post_check(post_process.DoesNotRun, 'extract sysroot archive'),
      api.post_check(post_process.MustRun, 'archive sysroot'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      # By default, use Portage as the build orchestrator for all build steps.
      api.build_menu.assert_step_uses_portage('install packages',
                                              'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_portage('build images',
                                              'ImageService/Create'),
  )

  # Use sysroot archive
  yield api.build_menu.test(
      'use-sysroot-archive',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'board1'
                  }
              },
              '$chromeos/sysroot_archive': {
                  'sysroot_enabled': {
                      'use_sysroot_archive': True,
                      'gs_bucket': 'foo',
                      'chromeos_start_version': 'R120-15650.0.0',
                      'chromeos_end_version': 'R120-15651.0.0',
                      'chromeos_cl_diff_counts': 310
                  }
              }
          }),
      api.post_check(post_process.MustRun, 'extract sysroot archive'),
      api.post_check(post_process.DoesNotRun, 'archive sysroot'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      # By default, use Portage as the build orchestrator for all build steps.
      api.build_menu.assert_step_uses_portage('install packages',
                                              'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_portage('build images',
                                              'ImageService/Create'),
  )

  yield api.build_menu.test(
      'custom-snapshot-commit',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'elm'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-postsubmit.{cros-version}-{bbid}'
              },
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True
              },
              'snapshot_commit': {
                  'host': 'test_host',
                  'project': 'test_project',
                  'ref': 'test_ref',
                  'id': 'test_id'
              }
          }),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.assert_step_uses_portage('install packages',
                                              'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_portage('build images',
                                              'ImageService/Create'),
  )
