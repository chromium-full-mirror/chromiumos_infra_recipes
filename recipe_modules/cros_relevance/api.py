# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api.depgraph import GetBuildDependencyGraphRequest
from PB.chromiumos.common import ProtoBytes as common_proto_bytes
from PB.chromiumos.generate_build_plan import GenerateBuildPlanRequest
from PB.chromiumos.generate_build_plan import GenerateBuildPlanResponse
from PB.testplans.common import ProtoBytes as testplans_proto_bytes
from PB.testplans.pointless_build import PointlessBuildCheckRequest
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api

import os


class CrosRelevanceApi(recipe_api.RecipeApi):
  """A module for determining if a build is unnecessary."""

  def initialize(self):
    """Initializes the module."""
    self._pointless_build_checker_path = None
    self._build_planner_path = None

  def get_necessary_builders(self, builder_configs, gerrit_changes,
                             gitiles_commit, name=None, test_builder_ids=[]):
    """Determines which builders must be run (and which can be skipped).

    This filters on preconfigured RunWhen rules, as well as on rules allowing
    skipping of image builders. Image builders are those that run the
    build_target recipe, producing an IMAGE_ZIP Chrome OS artifact.

    Args:
      builder_configs (list[chromiumos.BuilderConfig]): builder configs to
          consider for skipping.
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      name (str): The step name.
      test_builder_ids (list[BuilderConfig.Id]): test override

    Returns:
      list[str]: the names of the child builders that must be run.
    """
    with self.m.step.nest(name or 'plan builds') as step_result:
      self._ensure_binaries()
      request = GenerateBuildPlanRequest(
          gitiles_commit=common_proto_bytes(
              serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
                  gitiles_commit)), manifest_commit=gitiles_commit.id)
      request.builder_configs.extend(builder_configs)
      for gc in gerrit_changes:
        new_gc = request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))

      messages_path = self.m.path.mkdtemp(prefix='build-plan-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      self.m.file.write_raw('write input binaryproto', input_bin_file,
                            request.SerializeToString())

      cmd = [
          self._build_planner_path,
          'generate-plan',
          '--input_binary_pb',
          input_bin_file,
          '--output_binary_pb',
          output_bin_file,
      ]
      self.m.step('run planner', cmd, infra_step=True)

      test_resp = GenerateBuildPlanResponse(builds_to_run=test_builder_ids,)
      response_bin = self.m.file.read_raw(
          'read output file', output_bin_file,
          test_data=test_resp.SerializeToString())
      result = GenerateBuildPlanResponse()
      result.ParseFromString(response_bin)

      step_result.presentation.logs['planner_output'] = [str(result)]
      step_result.presentation.step_text = (
          '{} relevant, {} irrelevant builder configs'.format(
              len(result.builds_to_run),
              len(result.skip_for_global_build_irrelevance) + len(
                  result.skip_for_run_when_rules)))
      return [b.name for b in result.builds_to_run]

  def is_build_pointless(self, gerrit_changes, gitiles_commit, dep_graph,
                         test_is_pointless=False):
    """Determines if build(s) can be terminated early.

    If build_target is set, then the chromiumos workspace must have been
    checked out prior to calling this method. This is a requirement for
    BuildDependencyGraph checks.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      dep_graph (chromite.api.DepGraph): The dependency graph to compare the
          Gerrit changes against to test for build relevancy.
      test_is_pointless (bool): test override; sets whether build is pointless.

    Returns:
      bool: Whether the build can be terminated early.
    """
    with self.m.step.nest('pointless build check') as step_result:
      pointless_build = not self.is_depgraph_affected(
          gerrit_changes, gitiles_commit, dep_graph,
          test_is_pointless=test_is_pointless)
      if pointless_build:
        step_result.presentation.step_text = ('build is irrelevant')
        step_result.presentation.properties['pointless_build'] = True
      else:
        step_result.presentation.step_text = ('build is relevant')
      return pointless_build

  def is_depgraph_affected(self, gerrit_changes, gitiles_commit, dep_graph,
                           name=None, test_is_pointless=False):
    """Determines if a Gerrit Change affects a given dependency graph.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      dep_graph (chromite.api.DepGraph): The dependency graph to compare the
          Gerrit changes against to test for build relevancy.
      name (str): The step name to display, defaults to 'depgraph relevance
          check'.

    Returns:
      bool: Whether the given Gerrit Change affects the given dependency graph.
    """
    with self.m.step.nest(name or 'depgraph relevance check') as step_result:
      self._ensure_binaries()
      check_request = PointlessBuildCheckRequest(
          gitiles_commit=testplans_proto_bytes(
              serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
                  gitiles_commit)),
          manifest_commit=gitiles_commit.id,
          dep_graph=dep_graph,
      )
      for gc in gerrit_changes:
        new_gc = check_request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))

      messages_path = self.m.path.mkdtemp(prefix='pointless-build-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      self.m.file.write_raw('write input binaryproto', input_bin_file,
                            check_request.SerializeToString())

      cmd = [
          self._pointless_build_checker_path,
          'check-build',
          '--input_binary_pb',
          input_bin_file,
          '--output_binary_pb',
          output_bin_file,
      ]
      test_plan_res = self.m.step('run check', cmd, infra_step=True)

      test_resp = PointlessBuildCheckResponse()
      test_resp.build_is_pointless.value = test_is_pointless
      response_bin = self.m.file.read_raw(
          'read output file', output_bin_file,
          test_data=test_resp.SerializeToString())
      result = PointlessBuildCheckResponse()
      result.ParseFromString(response_bin)

      step_result.presentation.logs['relevance_output'] = [str(result)]
      return not bool(result.build_is_pointless.value)

  def get_dependency_graph(self, build_target, chroot):
    """Calculates the dependency graph for the build target & SDK

    Args:
      build_target (chromiumos.BuildTarget): The BuildTarget being built.
      chroot (chromiumos.Chroot): The chroot it is being run in.

    Returns:
      (chromite.api.DepGraph, chromite.api.DepGraph): A tuple of opaque
          dependency graph objects, with the first element being the dependency
          graph for the target and the second element the graph for the
          SDK/chroot.
    """
    with self.m.step.nest('dependency graph calculation'):
      resp = self.m.cros_build_api.DependencyService.GetBuildDependencyGraph(
          GetBuildDependencyGraphRequest(build_target=build_target,
                                         chroot=chroot))
      return resp.dep_graph, resp.sdk_dep_graph

  def _ensure_binaries(self):
    """Ensure this module's binaries are installed."""
    if self._pointless_build_checker_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure binaries'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._pointless_build_checker_path = (
            cipd_dir.join('pointless_build_checker'))
        self._build_planner_path = (cipd_dir.join('build_plan_generator'))
