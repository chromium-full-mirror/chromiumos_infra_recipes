# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from google.protobuf import struct_pb2


class CrosHistoryTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def build_with_passed_tests(self, tests):
    """Generate a struct for the 'build_target_test_status' property.

    Args:
      tests (list[str]): List of tests names that passed.

    Returns:
      Build: Containing the expected output properties.
    """
    build = build_pb2.Build(id=123, builder=build_pb2.BuilderID(builder='nami'))
    build.output.properties.update({'passed_tests': tests})
    return build

  @staticmethod
  def build_target_property(build_target):
    """Generate a struct for the 'build_target' property.

    Args:
      * build_target (str): The name of the build target.
    """
    return struct_pb2.Struct(
        fields={
            'build_target':
                struct_pb2.Value(
                    struct_value=struct_pb2.Struct(fields={
                        'name': struct_pb2.Value(string_value=build_target)
                    }))
        })