# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class CrosTestPlanApi(recipe_api.RecipeApi):
  """A module for generating and parsing test plans."""

  def initialize(self):
    self._test_planner_path = None

  def generate(self, builds, name=None):
    """Generate test plan.

    Args:
      * name (str): The step name.
      * builds (list[build_pb2.Build]): builds to test.

    Returns:
      GenerateTestPlanResponse of test plan.
    """
    with self.m.step.nest(name or 'generate test plan') as step:
      self._ensure_test_planner()

      messages_path = self.m.path.mkdtemp(prefix='test-plan-')
      input_file = messages_path.join('input.json')
      output_file = messages_path.join('output.json')

      request_proto = GenerateTestPlanRequest(
          chromiumos_checkout_root=str(self.m.cros_source.workspace_path),
          repo_tool_path=str(self.m.repo.repo_path), buildbucket_protos=[
              ProtoBytes(serialized_proto=Build.SerializeToString(build))
              for build in builds
          ])
      request_json = json_format.MessageToJson(request_proto)
      step.presentation.logs['request'] = [request_json]
      self.m.file.write_raw('write input json', input_file, request_json)

      cmd = [
          self._test_planner_path, 'gen-test-plan', '--input_json', input_file,
          '--output_json', output_file
      ]
      self.m.step('call test_planner', cmd)

      test_data = json_format.MessageToJson(
          self.test_api.generate_test_plan_response)
      response_json = self.m.file.read_raw('read output json', output_file,
                                           test_data=test_data)
      step.presentation.logs['response'] = [response_json]
      response_proto = json_format.Parse(response_json,
                                         GenerateTestPlanResponse(),
                                         ignore_unknown_fields=True)
      return response_proto

  def _ensure_test_planner(self):
    """Ensure the test_planner cli is installed."""
    if self._test_planner_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure test_planner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._test_planner_path = cipd_dir.join('test_plan_generator')
