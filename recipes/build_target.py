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

  def test(name, cq=True, build_target=None, artifact_pointless=False,
           pointless=False, args=None, **kwargs):
    """A test build, with BuildTargetProperties,

    Args:
      cq (bool): Whether this is a CQ build. Default: True
      build_target (str): The name of the build target, or None.
      artifact_pointless (bool): Whether the artifact prepare step replies
          POINTLESS.
      pointless (bool): Whether the build is pointless.
      args (list):  Arguments to pass to api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      A step_data object with both the build and the recipe input properties.
    """
    args = args or []
    kwargs['cq'] = cq
    build_target = build_target or 'amd64-generic'
    ret = api.test_util.test_child_build(build_target, **kwargs).build
    if artifact_pointless:
      ret += api.build_menu.set_build_api_return(
          'prepare artifacts', 'ArtifactsService/PrepareForBuild',
          '{"build_relevance": "POINTLESS"}')
    if pointless:
      ret += api.build_menu.set_pointless_return(True)
    return api.test(name, ret, *args)

  # Normal CQ build, with one gerrit_change.
  yield test('basic')

  # This covers the Relevance check.
  yield test('prepare-for-build-pointless', artifact_pointless=True)

  # This covers the env_info.pointless check.
  yield test('pointless-build-check', pointless=True)

  yield test('run-exit-install', cq=False,
             builder='arm64-generic-kernel-v5_4-buildtest-postsubmit')

  yield test('no-run-tests', build_target='grunt')

  yield test('run-exit-tests', cq=False,
             builder='amd64-generic-exit-after-unittests')

  yield test(
      'install-packages-fail', args=[
          api.build_menu.set_build_api_return('install packages',
                                              'SysrootService/InstallPackages',
                                              '', retcode=1)
      ])

  yield test(
      'bundle-fail', args=[
          api.build_menu.set_build_api_return(
              'upload artifacts', 'ArtifactsService/BundleArtifacts', '',
              retcode=1)
      ])
