# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class BuilderMetadataTestApi(recipe_test_api.RecipeTestApi):

  def look_up_builder_metadata(self, parent_step, metadata):
    step_name = parent_step + (
        '.' if parent_step else ''
    ) + 'look up builder metadata.call chromite.api.PackageService/GetBuilderMetadata.read output file'
    return self.step_data(step_name, self.m.raw_io.stream_output(metadata))
