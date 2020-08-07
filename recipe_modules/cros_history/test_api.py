# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder as builder_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon

from google.protobuf import struct_pb2


class CrosHistoryTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def build_with_passed_tests(self, tests):
    """Generate a test build with the 'passed_tests' property.

    Args:
      tests (list[str]): List of tests names that passed.

    Returns:
      Build: Containing the expected 'passed_tests' output property.
    """
    build = build_pb2.Build(id=123,
                            builder=builder_pb2.BuilderID(builder='atlas-cq'))
    build.output.properties.update({'passed_tests': tests})
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return build

  def build_with_failed_tests(self, builder_names):
    """Generate a test build with the 'test_failures' property.

    Args:
      tests (list[str]): List of builder names that failed hw testing.

    Returns:
      Build: Containing the expected 'test_failures' output property.
    """
    build = build_pb2.Build(id=123,
                            builder=builder_pb2.BuilderID(builder='atlas-cq'))

    build.output.properties.update({
        'test_failures': {
            "hw_test_failures": [{
                'test_spec':
                    jsonpb.MessageToJson(
                        HwTestUnit(
                            common=TestUnitCommon(builder_name=builder_name)))
            } for builder_name in builder_names],
            "needs_bisection": False
        }
    })

    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return build
