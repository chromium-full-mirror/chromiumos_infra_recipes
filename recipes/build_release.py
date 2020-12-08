# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for release."""

DEPS = [
    'build_menu',
    'test_util',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.recipes.chromeos.build_target import BuildTargetProperties

PROPERTIES = BuildTargetProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  # Artifacts are frequently of use even if the build failed.  For example, it
  # is likely that the developer will want to see the ebuild logs from install
  # packages when that step fails, or even if build images fail afterward.
  # Thus, we track raise_upload_failure to avoid raising an upload failure if
  # the build has already failed. See also crbug/1086630.
  raise_upload_failure = True
  try:
    if api.build_menu.bootstrap_sysroot_and_install_packages(config, packages):
      if api.build_menu.build_and_test_images(config):
        api.build_menu.upload_prebuilts(config)
        api.build_menu.sign_images(config)
        api.build_menu.generate_payloads(config)
  except StepFailure:
    raise_upload_failure = False
    raise
  finally:
    try:
      api.build_menu.upload_artifacts(config,
                                      failing_build=not raise_upload_failure)
    except StepFailure:
      # TODO(crbug/1086630): We do not need to catch StepFailure here after
      # 2020-12-31.
      if raise_upload_failure:
        raise


def GenTests(api):

  # Normal release build.
  yield api.build_menu.test(
      'release-build', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess))

  # Release build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1))

  # Release build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail', api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/BundleArtifacts',
                                          retcode=1))

  # Release build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/BundleArtifacts',
                                          retcode=1))
