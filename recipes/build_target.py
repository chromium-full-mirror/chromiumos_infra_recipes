# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image."""

DEPS = [
    'build_menu',
    'cros_artifacts',
    'cros_infra_config',
    'test_util',
]

from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process
from PB.recipes.chromeos.build_target import BuildTargetProperties

PROPERTIES = BuildTargetProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder() as config:
    if config:
      DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  if not api.build_menu.setup_workspace_and_chroot():
    return

  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return
  packages = env_info.packages

  # Artifacts are frequently of use even if the build failed.  For example, it
  # is likely that the developer will want to see the ebuild logs from install
  # packages when that step fails, or even if build images fail afterward. See
  # also crbug/1086630.
  #
  # TODO(crbug/1053703): The if statements from here to the end should be
  # removed as we break build_target.py into the various builders.  In
  # particular, RUN_EXIT now means "run through this step, and then upload
  # any artifacts and exit."
  #
  # In the case of install_packages.run_spec saying to not run, there are likely
  # to be no artifacts to upload, in which case the upload_artifacts call should
  # "bundle everything", and then "upload all none" of the artifacts.

  forgive_upload_failure = False
  try:
    install_spec = config.build.install_packages.run_spec
    ebuilds_spec = config.unit_tests.ebuilds_run_spec
    if api.cros_infra_config.should_run(install_spec):
      api.build_menu.bootstrap_sysroot_and_install_packages(config, packages)

    if not api.cros_infra_config.should_exit(install_spec):
      api.build_menu.build_and_test_images(
          config=config,
          run_tests=api.cros_infra_config.should_run(ebuilds_spec))

    if (not api.cros_infra_config.should_exit(install_spec) and
        not api.cros_infra_config.should_exit(ebuilds_spec)):
      api.build_menu.upload_prebuilts(config)
  except StepFailure:
    # A StepFailure means build failed, we want to forgive an upload failure.
    forgive_upload_failure = True
    raise
  finally:
    # Always try to upload artifacts.  If there are none, it is a noop.
    try:
      api.build_menu.upload_artifacts(config)
    except StepFailure:
      # TODO(crbug/1086630): We do not need to catch StepFailure here after
      # 2020-12-31.
      # Do not fail if we already did.  See also crrev.com/c/2241753.
      if not forgive_upload_failure:
        raise


def GenTests(api):

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'cq-build', api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test(
      'pointless-cq-build',
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True, pointless=True)

  # Normal postsubmit build.
  yield api.build_menu.test(
      'postsubmit-build',
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess))

  # Postsubmit build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusAnyFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages', '',
                                          retcode=1), cq=True)

  # Postsubmit build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail', api.post_check(post_process.StatusAnyFailure),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/BundleArtifacts',
                                          '', retcode=1), cq=True)

  # This covers the Relevance check.
  yield api.build_menu.test(
      'prepare-for-build-pointless',
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True,
      input_properties=BuildTargetProperties(artifact_build=True),
      artifact_pointless=True)

  yield api.build_menu.test(
      'run-exit-install',
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      builder='arm64-generic-kernel-v5_4-buildtest-postsubmit')

  # This builder has no output artifacts.
  yield api.build_menu.test(
      'no-run-tests', api.post_check(post_process.DoesNotRun,
                                     'upload artifacts'),
      api.post_check(post_process.StatusSuccess), build_target='grunt',
      builder='grunt-unittest-only-postsubmit')

  yield api.build_menu.test(
      'run-exit-tests', api.post_check(post_process.MustRun,
                                       'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      builder='amd64-generic-exit-after-unittests')
