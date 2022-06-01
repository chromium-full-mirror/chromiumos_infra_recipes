# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds and uploads the Chromium OS toolchain."""

DEPS = [
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine import post_process
from PB.chromite.api.sdk import BuildPrebuiltsRequest, \
  UploadPrebuiltPackagesRequest


def RunSteps(api):
  # Unlike normal CrOS builds, the SDK has no concept of pinned CrOS manifest
  # or specific Chrome version.  Use a datestamp instead.
  version = api.time.utcnow().strftime('%Y.%m.%d.%H%M%S')
  api.step.empty('new SDK version', step_text=version)

  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():

    with api.step.nest('build SDK packages'):
      api.cros_build_api.SdkService.BuildPrebuilts(
          BuildPrebuiltsRequest(chroot=api.cros_sdk.chroot))

    with api.step.nest('upload prebuilt packages'):
      api.cros_build_api.SdkService.UploadPrebuiltPackages(
          UploadPrebuiltPackagesRequest(
              chroot=api.cros_sdk.chroot,
              # Upload to a different location than chromiumos-sdk.
              # TODO(b/218322901): Decide if we want to keep this
              # location or change it.
              prepend_version='test-chroot',
              version=version,
              upload_location='gs://chromeos-prebuilt'))


def GenTests(api):
  yield api.build_menu.test(
      'sucessful-run', api.post_check(post_process.MustRun,
                                      'build SDK packages'),
      api.post_check(post_process.MustRun, 'upload prebuilt packages'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.build_menu.test(
      'build_sdk_packages-failed',
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('build SDK packages',
                                          'SdkService/BuildPrebuilts',
                                          retcode=1),
      api.post_process(post_process.DropExpectation))

  yield api.build_menu.test(
      'upload_prebuilt_packages-failed',
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('upload prebuilt packages',
                                          'SdkService/UploadPrebuiltPackages',
                                          retcode=1),
      api.post_process(post_process.DropExpectation))
