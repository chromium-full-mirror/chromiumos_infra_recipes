# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class CrosTestPlanApi(recipe_api.RecipeApi):
  """A module for generating and parsing test plans."""

  def initialize(self):
    self._test_planner_path = None

  def generate(self, builds, gerrit_changes, manifest_commit, name=None):
    """Generate test plan.

    Args:
      * name (str): The step name.
      * builds (list[build_pb2.Build]): builds to test.
      * gerrit_changes (list[common_pb2.GerritChange]): changes that were inputs
          for these builds, or empty.
      * manifest_commit (common_pb2.GitilesCommit): manifest commit for build.

    Returns:
      GenerateTestPlanResponse of test plan.
    """
    with self.m.step.nest(name or 'generate test plan') as presentation:
      self._ensure_test_planner()

      request_proto = GenerateTestPlanRequest(
          manifest_commit=manifest_commit.id, gitiles_commit=ProtoBytes(
              serialized_proto=GitilesCommit.SerializeToString(
                  manifest_commit)),
          gerrit_changes=[
              ProtoBytes(serialized_proto=GerritChange.SerializeToString(gc))
              for gc in gerrit_changes or []
          ], buildbucket_protos=[
              ProtoBytes(serialized_proto=Build.SerializeToString(build))
              for build in builds
          ])
      request_json = json_format.MessageToJson(request_proto)
      presentation.logs['planner_input'] = [str(request_json)]

      messages_path = self.m.path.mkdtemp(prefix='test-plan-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      self.m.file.write_raw('write input binaryproto', input_bin_file,
                            request_proto.SerializeToString())

      cmd = [
          self._test_planner_path, 'gen-test-plan', '--input_binary_pb',
          input_bin_file, '--output_binary_pb', output_bin_file
      ]
      # We already have a local copy of the manifest.  Use it, rather than
      # fetching it from the network.
      cmd.extend(['--manifest_file', self.m.cros_source.branch_manifest_file])

      self.m.step('call test_planner', cmd, infra_step=True)

      response_bin = self.m.file.read_raw(
          'read output file', output_bin_file,
          test_data=self.test_api.generate_test_plan_response.SerializeToString(
          ))
      response_proto = GenerateTestPlanResponse.FromString(response_bin)

      presentation.logs['planner_output'] = [str(response_proto)]
      return response_proto

  def _ensure_test_planner(self):
    """Ensure the test_planner cli is installed."""
    if self._test_planner_path:
      return

    with self.m.step.nest('ensure test_planner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._test_planner_path = cipd_dir.join('test_plan_generator')
