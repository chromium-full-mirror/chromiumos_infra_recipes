# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for Postsubmit."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'bot_scaling',
    'build_menu',
    'cros_history',
    'cros_infra_config',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):

  if api.cros_infra_config.is_staging:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=4,
                                   max_drop_ratio=.75)  # pragma: nocover

  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config)


def DoRunSteps(api, config):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was not relevant.')
  packages = env_info.packages

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      api.build_menu.upload_prebuilts(config)
      api.build_menu.create_containers(config)
      api.build_menu.build_and_test_images(config)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

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
  return None


def GenTests(api):

  # Normal postsubmit build.
  yield api.build_menu.test(
      'postsubmit-build',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess))

  # Pointless postsubmit build.
  yield api.build_menu.test(
      'pointless-postsubmit-build', api.post_check(post_process.StatusSuccess),
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
          }}), api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1))

  # Postsubmit build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1))

  # Postsubmit build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1))

  yield api.build_menu.test(
      'run-exit-install',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      builder='arm64-generic-kernel-v5_4-buildtest-postsubmit')

  # This builder has no output artifacts, and builds no images. (In the test
  # data...)
  yield api.build_menu.test(
      'no-run-tests',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess), build_target='grunt',
      builder='grunt-postsubmit')
