# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.pointless_build import PointlessBuildCheckRequest
from PB.chromiumos.pointless_build import PointlessBuildCheckResponse
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api

class CrosRelevanceApi(recipe_api.RecipeApi):
  """A module for determining if a build is unnecessary."""

  def initialize(self):
    """Initializes the module."""
    self._pointless_build_checker_path = None

  def is_build_pointless(self, build):
    """Determines if the build can be terminated early.

    Args:
      build (build_pb2.Build): The child builder to check.

    Returns:
      bool: Whether the build can be terminated early.
    """
    self._ensure_pointless_build_checker()
    check_request = PointlessBuildCheckRequest()
    check_request.chromiumos_workspace_checkout_root = str(
        self.m.cros_source.master_path)
    check_request.repo_tool_path = str(self.m.repo.repo_path)
    check_request.buildbucket_proto.serialized_proto = (
        build_pb2.Build.SerializeToString(build))
    cmd = [
        self._pointless_build_checker_path,
        'check-build',
        '--input_json',
        self.m.json.input(jsonpb.MessageToDict(check_request)),
        '--output_json',
        self.m.json.output(),
    ]
    test_plan_res = self.m.step('pointless build check', cmd)
    output = test_plan_res.json.output
    result = jsonpb.ParseDict(output, PointlessBuildCheckResponse(),
                              ignore_unknown_fields=True)
    return result.build_is_pointless

  def _ensure_pointless_build_checker(self):
    """Ensure the pointless_build_checker binary is installed."""
    if self._pointless_build_checker_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure pointless_build_checker'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._pointless_build_checker_path = (
            cipd_dir.join('pointless_build_checker'))
