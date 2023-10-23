# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for end-to-end test planning."""

import json

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from recipe_engine import recipe_api

CONFIG_INTERNAL_CHECKOUT = 'src/config-internal'
INFRA_CONFIG_URL = 'https://chrome-internal.googlesource.com/chromeos/infra/config'
HELP_STDOUT = '''Generate testing config for specified release builders.

Usage: ./generate_test_config [options]
Usage: ./generate_test_config [options] all
Usage: ./generate_test_config [options] coral-release-main,staging-kevin-release-main

Options:
  ...
  -b, --branch                  Tell the tool what branch we're on. Only for
'''


class CrosTestPlanApi(recipe_api.RecipeApi):
  """A module for generating and parsing test plans."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  def get_target_test_requirements(self, builders=None):
    """Fetch target test requirements config.

    Args:
      builders (list[str]): optional list of builder names to generate config for,
        e.g. coral-release-main or staging-kevin-release-main. If not specified,
        either the invoking builder or its children (if the invoking builder name
        contains 'orchestrator') will be used.
    Returns:
      JSON structure of target test requirements.
    """
    if self._properties.generate_target_test_requirements_from_source:
      return self.generate_target_test_requirements_config(builders=builders)
    # TODO(b/209487309): Remove this logic -- we know all callers of this
    # function (just paygen) and we'd like to switch to generation anyways.
    with self.m.step.nest('fetch target test requirements file'):
      source_gitiles_repo = (
          str(self._properties.source_gitiles_repo)
          if self._properties.source_gitiles_repo else 'chromeos/infra/config')
      source_gitiles_branch = (
          str(self._properties.source_gitiles_branch)
          if self._properties.source_gitiles_branch else 'main')
      target_test_requirements_path = (
          str(self._properties.target_test_requirements_path)
          if self._properties.target_test_requirements_path else
          'testingconfig/generated/target_test_requirements.binaryproto')

      data = self.m.gitiles.get_file(
          'chrome-internal.googlesource.com', source_gitiles_repo,
          target_test_requirements_path,
          ref=self.m.git.get_branch_ref(source_gitiles_branch), public=False)
      if data:
        return json.loads(data)
      return None

  def generate_target_test_requirements_config(self, builders=None,
                                               paygen=False):
    """Generate target test requirements config in config-internal using
      ./board_config/generate_test_config. Assumes config-internal is
      checked out at `src_state.workspace_path/CONFIG_INTERNAL_CHECKOUT`.

    Args:
      builders (list[str]): optional list of builder names to generate config for,
        e.g. coral-release-main or staging-kevin-release-main. If not specified,
        either the invoking builder or its children (if the invoking builder name
        contains 'orchestrator') will be used.
      paygen (bool): If true, generate paygen testing requirements instead of
        standard per-build-target test requirements.

    Returns:
      JSON structure of target test requirements or None.
    """
    with self.m.step.nest('generate target test requirements'):
      with self.m.context(cwd=self.m.src_state.workspace_path):
        if not builders:
          builder_name = self.m.buildbucket.build.builder.builder
          if 'orchestrator' in builder_name:
            # If the build is an orchestrator, we want the config for all of the
            # child builders.
            builders = [
                spec.name for spec in
                self.m.cros_infra_config.config.orchestrator.child_specs
            ]
          else:
            # Otherwise, assume we want config for the invoking builder.
            builders = [builder_name]
        with self.m.context(
            cwd=self.m.src_state.workspace_path.join(CONFIG_INTERNAL_CHECKOUT)):
          cmd = ['./board_config/generate_test_config', ','.join(builders)]
          if paygen:
            cmd.append('--paygen')

          # If --branch is supported on this branch, use it.
          # TODO(b/262388770): Maybe in many years we can do this
          # unconditionally.
          help_message = self.m.easy.stdout_step(
              'get supported flags',
              ['./board_config/generate_test_config', '-h'],
              test_stdout=HELP_STDOUT)
          config = self.m.cros_infra_config.config
          if '--branch' in str(help_message) and config:
            branch = config.orchestrator.gitiles_commit.ref
            if branch:
              cmd.extend(['--branch', branch[len('refs/heads/'):]])

          def test_stdout():
            if paygen:
              return json.dumps({builder: {} for builder in builders})
            return ''

          data = self.m.easy.stdout_step('generate_test_config', cmd,
                                         test_stdout=test_stdout)
          return json.loads(data) if data else None

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
      request_proto = GenerateTestPlanRequest(
          manifest_commit=manifest_commit.id, gitiles_commit=ProtoBytes(
              serialized_proto=GitilesCommit.SerializeToString(
                  manifest_commit, deterministic=True)), gerrit_changes=[
                      ProtoBytes(
                          serialized_proto=GerritChange.SerializeToString(
                              gc, deterministic=True))
                      for gc in gerrit_changes or []
                  ], buildbucket_protos=[
                      ProtoBytes(
                          serialized_proto=Build.SerializeToString(
                              build, deterministic=True)) for build in builds
                  ])
      presentation.logs['planner_input'] = json_format.MessageToJson(
          request_proto)

      messages_path = self.m.path.mkdtemp(prefix='test-plan-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      self.m.file.write_raw('write input binaryproto', input_bin_file,
                            request_proto.SerializeToString(deterministic=True))

      cmd = [
          'gen-test-plan', '--input_binary_pb', input_bin_file,
          '--output_binary_pb', output_bin_file
      ]
      # We already have a local copy of the manifest.  Use it, rather than
      # fetching it from the network.
      cmd.extend(['--manifest_file', self.m.cros_source.branch_manifest_file])

      if self._properties.source_gitiles_repo:
        cmd.extend(['--gitiles_repo', self._properties.source_gitiles_repo])
      if self._properties.source_gitiles_branch:
        cmd.extend(['--gitiles_branch', self._properties.source_gitiles_branch])
      if self._properties.board_priority_config_path:
        cmd.extend([
            '--board_priority_config',
            self._properties.board_priority_config_path
        ])
      if self._properties.source_tree_test_config_path:
        cmd.extend([
            '--source_tree_test_config',
            self._properties.source_tree_test_config_path
        ])
      if self._properties.target_test_requirements_path:
        cmd.extend([
            '--target_test_requirements',
            self._properties.target_test_requirements_path
        ])
      if self._properties.generate_target_test_requirements_from_source:
        with self.m.context(cwd=self.m.src_state.workspace_path):
          config_internal_path = self.m.src_state.workspace_path.join(
              CONFIG_INTERNAL_CHECKOUT)
          cmd.extend(['--target_test_requirements_repo', config_internal_path])
          config = self.m.cros_infra_config.config
          if config and config.orchestrator.gitiles_commit.ref:
            cmd.extend([
                '--target_test_requirements_branch',
                config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]
            ])
      if self._properties.use_prod_config:
        cmd.append('--use_prod_config')

      self.m.gobin.call('test_plan_generator', cmd,
                        step_name='call test_planner', infra_step=True)

      response_bin = self.m.file.read_raw(
          'read output file', output_bin_file,
          test_data=self.test_api.generate_test_plan_response.SerializeToString(
              deterministic=True))
      response_proto = GenerateTestPlanResponse.FromString(response_bin)

      presentation.logs['planner_output'] = str(response_proto)
      return response_proto

  def get_test_plan_summary(self, test_plan):
    """Return a mapping of display name to criticality.

    Args:
      test_plan (GenerateTestPlanResponse): The test plan to summarize.

    Returns:
      test_to_crit_map (dict{string: bool}): Map of test display name to
        criticality.
    """
    test_to_crit_map = {}
    for unit in test_plan.hw_test_units:
      for test in unit.hw_test_cfg.hw_test:
        test_to_crit_map[test.common.display_name] = test.common.critical.value

    for unit in test_plan.direct_tast_vm_test_units:
      for test in unit.tast_vm_test_cfg.tast_vm_test:
        test_to_crit_map[test.common.display_name] = test.common.critical.value

    for unit in test_plan.tast_gce_test_units:
      for test in unit.tast_gce_test_cfg.tast_gce_test:
        test_to_crit_map[test.common.display_name] = test.common.critical.value

    return test_to_crit_map
