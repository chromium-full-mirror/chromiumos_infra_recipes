# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds and uploads the Chromium OS toolchain."""

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.chromite.api.sdk import CreateBinhostCLsRequest
from PB.chromite.api.sdk import UploadPrebuiltPackagesRequest
from recipe_engine import post_process


DEPS = [
    "recipe_engine/step",
    "recipe_engine/time",
    "build_menu",
    "cros_build_api",
    "cros_sdk",
]

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

PREBUILT_UPLOAD_BUCKET = "gs://chromeos-prebuilt"
# The chromeos-sdk builder uses 'chroot' as VERSION_PREFIX.
# We use a different prefix to avoid conflicts.
VERSION_PREFIX = "build_toolchain"


def RunSteps(api):
  # Unlike normal CrOS builds, the SDK has no concept of pinned CrOS manifest
  # or specific Chrome version.  Use a datestamp instead.
  version = api.time.utcnow().strftime("%Y.%m.%d.%H%M%S")
  api.step.empty("new SDK version", step_text=version)

  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():

    with api.step.nest("build SDK packages"):
      api.cros_build_api.SdkService.BuildPrebuilts(
          BuildPrebuiltsRequest(chroot=api.cros_sdk.chroot))

    with api.step.nest("upload prebuilt packages"):
      api.cros_build_api.SdkService.UploadPrebuiltPackages(
          UploadPrebuiltPackagesRequest(
              chroot=api.cros_sdk.chroot,
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=PREBUILT_UPLOAD_BUCKET,
          ))

    with api.step.nest("create binhost CLs"):
      api.cros_build_api.SdkService.CreateBinhostCLs(
          CreateBinhostCLsRequest(
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=PREBUILT_UPLOAD_BUCKET,
          ))


def GenTests(api):
  yield api.build_menu.test(
      "sucessful-run", api.post_check(post_process.MustRun,
                                      "build SDK packages"),
      api.post_check(post_process.MustRun, "upload prebuilt packages"),
      api.post_check(post_process.MustRun, "create binhost CLs"),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.build_menu.test(
      "build_sdk_packages-failed",
      api.post_check(post_process.MustRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return("build SDK packages",
                                          "SdkService/BuildPrebuilts",
                                          retcode=1),
      api.post_process(post_process.DropExpectation))

  yield api.build_menu.test(
      "upload_prebuilt_packages-failed",
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return(
          "upload prebuilt packages",
          "SdkService/UploadPrebuiltPackages",
          retcode=1,
      ), api.post_process(post_process.DropExpectation))

  yield api.build_menu.test(
      "create-binhost-cls-failed", api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return("create binhost CLs",
                                          "SdkService/CreateBinhostCLs",
                                          retcode=1),
      api.post_process(post_process.DropExpectation))
