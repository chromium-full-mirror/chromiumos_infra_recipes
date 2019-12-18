# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import struct_pb2


class BuildPlanTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the build_plan module."""

  def input_proto(self, snapshot, build_target):
    """Generate an instance of Build.Input.

    Args:
      * snapshot(GitilesCommit): The snapshot of the build.
      * build_target (str): The name of the build target.
    """
    return build_pb2.Build.Input(
        properties=self.m.cros_history.build_target_property(build_target),
        gerrit_changes=[common_pb2.GerritChange(change=1234)],
        gitiles_commit=snapshot)
