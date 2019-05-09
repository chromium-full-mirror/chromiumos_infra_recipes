# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from google.protobuf import struct_pb2


class CrosHistoryTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def test_status_property(self, build_target_to_status):
    """Generate a struct for the 'build_target_test_status' property.

    Args:
      * dict[str, str]: A map from build target name to status.
    """
    return struct_pb2.Struct(
        fields={
            'build_target_test_status':
                struct_pb2.Value(
                    struct_value=struct_pb2.Struct(
                        fields={
                            build_target: struct_pb2.Value(string_value=status)
                            for build_target, status in build_target_to_status
                            .items()
                        }))
        })
