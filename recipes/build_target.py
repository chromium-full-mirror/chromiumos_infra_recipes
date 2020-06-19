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
from PB.recipes.chromeos.build_target import BuildTargetProperties

PROPERTIES = BuildTargetProperties


def RunSteps(api, properties):
  build_target = properties.build_target
  with api.build_menu.configure_builder(build_target) as config:
    if config:
      DoRunSteps(api, config, build_target, properties)


def DoRunSteps(api, config, build_target, properties):
  # TODO(crbug/1053703): artifact_build is something that we can remove when we
  # split up build_target.py into individual builders, since we will know
  # whether it is True or False based on what recipe we are.
  artifact_build = api.cros_artifacts.has_output_artifacts(
      config.artifacts.artifacts_info)

  if not api.build_menu.setup_workspace_and_chroot(
      artifact_build=artifact_build,
      forced_relevant=properties.force_relevant_build):
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
      api.build_menu.bootstrap_sysroot_and_install_packages(
          config, packages, artifact_build=artifact_build)

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
  yield api.build_menu.test('cq-build', cq=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test('pointless-cq-build', cq=True, pointless=True)

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test('postsubmit-build')

  # Postsubmit build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages', '',
                                          retcode=1), cq=True)

  # Postsubmit build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/BundleArtifacts',
                                          '', retcode=1), cq=True)

  # This covers the Relevance check.
  yield api.build_menu.test('prepare-for-build-pointless', cq=True,
                            artifact_pointless=True)

  yield api.build_menu.test(
      'run-exit-install',
      builder='arm64-generic-kernel-v5_4-buildtest-postsubmit')

  yield api.build_menu.test('no-run-tests', build_target='grunt', cq=True)

  yield api.build_menu.test('run-exit-tests',
                            builder='amd64-generic-exit-after-unittests')
