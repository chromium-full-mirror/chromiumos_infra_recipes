# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for Android uprev.

The target Android package/version to uprev is specified via input properties,
for example:

"$chromeos/android": {
  "android_package": "android-vm-rvc",
  "android_version": "7444938"
}
"""

DEPS = [
    'recipe_engine/swarming',
    'recipe_engine/properties',
    'android',
    'build_menu',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config)


def DoRunSteps(api, config):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  # Bootstrap sysroot, and skip the rest if android is not revved at all.
  api.build_menu.bootstrap_sysroot(config)
  if not api.android.uprev(api.build_menu.chroot, api.build_menu.sysroot):
    return

  # Artifacts are frequently of use even if the build failed.  For example, it
  # is likely that the developer will want to see the ebuild logs from install
  # packages when that step fails, or even if build images fail afterward.
  # Thus, we track raise_upload_failure to avoid raising an upload failure if
  # the build has already failed. See also crbug/1086630.
  raise_upload_failure = True
  try:
    if api.build_menu.install_packages(config, packages):
      # We have no steps following build_and_test_images, so we don't need to
      # check the return value.
      api.build_menu.build_and_test_images(config)
  except StepFailure:
    raise_upload_failure = False
    raise
  finally:
    try:
      api.build_menu.upload_artifacts(config)
    except StepFailure:
      # TODO(crbug/1086630): We do not need to catch StepFailure here after
      # 2020-12-31.
      if raise_upload_failure:
        raise


def GenTests(api):
  # Normal Android uprev build.
  yield api.build_menu.test(
      'basic',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.android.uprev_props(), api.android.set_mark_stable_success(),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess))

  # Android uprev build where uprev is not needed.
  yield api.build_menu.test(
      'android-not-revved',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.android.uprev_props(),
      api.android.set_mark_stable_early_exit(),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess))

  # Android uprev build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.android.uprev_props(), api.android.set_mark_stable_success(),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure))

  # Android uprev build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.android.uprev_props(), api.android.set_mark_stable_success())

  # Android uprev build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}), api.android.uprev_props(), api.android.set_mark_stable_success(),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure))
