# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image with unit tests."""

DEPS = [
    'build_menu',
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

  api.build_menu.setup_workspace_and_chroot()

  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return
  packages = env_info.packages

  forgive_upload_failure = False
  try:
    api.build_menu.bootstrap_sysroot_and_install_packages(config, packages)
    api.build_menu.build_and_test_images(config)
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

  def test(name, cq=True, build_target=None, pointless=False, args=None,
           **kwargs):
    """A test build, with BuildTargetProperties,

    Args:
      cq (bool): Whether this is a CQ build. Default: True
      build_target (str): The name of the build target, or None.
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
    if pointless:
      ret += api.build_menu.set_pointless_return(True)
    return api.test(name, ret, *args)

  # Normal CQ build, with one gerrit_change.
  yield test('basic')

  # This covers the env_info.pointless check.
  yield test('pointless-build-check', pointless=True)

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
