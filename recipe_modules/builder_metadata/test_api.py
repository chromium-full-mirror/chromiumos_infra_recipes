# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

BUILDER_METADATA = """
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


class BuilderMetadataTestApi(recipe_test_api.RecipeTestApi):

  def mock_metadata(self, parent_step='', metadata=BUILDER_METADATA):
    step_name = parent_step + ('.' if parent_step else '') + (
        'look up builder metadata.call chromite.api.PackageService/'
        'GetBuilderMetadata.read output file')
    return self.step_data(step_name, self.m.raw_io.stream_output(metadata))
