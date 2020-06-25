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

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test('cq-build', cq=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test('pointless-cq-build', cq=True, pointless=True)

  # Normal postsubmit build.
  yield api.build_menu.test('postsubmit-build')

  yield api.build_menu.test(
      'install-packages-fail',
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages', '',
                                          retcode=1), cq=True)

  yield api.build_menu.test(
      'bundle-fail',
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/BundleArtifacts',
                                          '', retcode=1), cq=True)
