# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the builder_metadata recipe module."""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_menu',
    'builder_metadata',
    'cros_build_api',
    'cros_sdk',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.step.nest('first-lookup'):
    first_metadata = api.builder_metadata.look_up_builder_metadata(
        test_data=True)
  with api.step.nest('second-lookup'):
    second_result = api.builder_metadata.look_up_builder_metadata(
        test_data=True)
  api.assertions.assertEqual(first_metadata, second_result)

  api.build_menu.packages_installed = False
  with api.assertions.assertRaises(api.step.StepFailure):
    api.builder_metadata.look_up_builder_metadata()
  api.build_menu.packages_installed = True

  # Test model metadata comes from the test response for
  # cros_build_api.PackageService.GetBuilderMetadata().
  models = api.builder_metadata.get_models()
  api.assertions.assertEqual(models, ['eve'])


def GenTests(api):
  builder_metadata = """
    build_target_metadata {
      build_target: "eve"
      android_container_branch: "git_rvc-arc"
      android_container_target: "bertha"
      android_container_version: "7978506"
      arc_use_set: true
      ec_firmware_version: "eve_v1.1.6659-ba2088ed3"
      kernel_version: "5.4.163-r2827"
      main_firmware_version: "Google_Eve.9584.230.0"
    }
    model_metadata {
      model_name: "eve"
      ec_firmware_version: "eve_v1.1.6659-ba2088ed3"
      firmware_key_id: "EVE"
      main_readonly_firmware_version: "Google_Eve.9584.107.0"
      main_readwrite_firmware_version: "Google_Eve.9584.230.0"
    }
    """

  yield api.test(
      'first-lookup',
      api.builder_metadata.look_up_builder_metadata('first-lookup',
                                                    builder_metadata),
      api.post_check(post_process.MustRun,
                     ('first-lookup.look up builder metadata.call chromite.api.'
                      'PackageService/GetBuilderMetadata')))

  yield api.test(
      'second-lookup',
      api.post_check(post_process.MustRun,
                     'second-lookup.look up builder metadata'),
      api.post_check(
          post_process.DoesNotRun,
          ('second-lookup.look up builder metadata.call chromite.api.'
           'PackageService/GetBuilderMetadata')))
