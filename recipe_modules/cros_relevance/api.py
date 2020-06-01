# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple

from PB.chromite.api.depgraph import GetBuildDependencyGraphRequest
from PB.chromite.api.depgraph import GetToolchainPathsRequest
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
    # Toolchain changes have been detected.
    self._toolchain_cls_applied = False

  @property
  def toolchain_cls_applied(self):
    """Whether there are toolchain CLs applied to the source tree."""
    return self._toolchain_cls_applied

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
    with self.m.step.nest(name or 'plan builds') as presentation:
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
      presentation.logs['planner_input'] = [str(request)]
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
      result = GenerateBuildPlanResponse.FromString(response_bin)

      presentation.logs['planner_output'] = [str(result)]
      presentation.step_text = (
          '{} relevant, {} irrelevant builder configs'.format(
              len(result.builds_to_run),
              len(result.skip_for_global_build_irrelevance) +
              len(result.skip_for_run_when_rules)))
      return [b.name for b in result.builds_to_run]

  def is_build_pointless(self, gerrit_changes, gitiles_commit, dep_graph,
                         force_relevant=False, test_value=None):
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
      force_relevant (bool): Whether to always declare the build relevant.
      test_value (bool): The answer to use for testing.  Default: build is not
          pointless.

    Returns:
      bool: Whether the build can be terminated early.
    """
    if not gerrit_changes or force_relevant or self.toolchain_cls_applied:
      # If there are no CLs, then this is not a CQ run and should never be
      # treated as pointless.  Likewise if force_relevant is set.
      return False
    with self.m.step.nest('pointless build check') as presentation:
      # We need to invert the value of test_value, since we were asked if the
      # build was pointless, and we're calling a function that returns True if
      # the build is relevant.  We want to pass True in the case where the
      # argument is None.
      relevant = self.is_depgraph_affected(gerrit_changes, gitiles_commit,
                                           dep_graph, test_value=not test_value)
      # TODO(seanabraham): stop writing 'pointless_build' property once Plx
      # scripts have switched over to 'relevant_build'.
      presentation.properties['pointless_build'] = not relevant
      presentation.properties['relevant_build'] = relevant
      presentation.step_text = ('build is relevant'
                                if relevant else 'build is irrelevant')
      return not relevant

  def _are_paths_affected(self, gerrit_changes, gitiles_commit, relevant_paths,
                          test_value=None, name=None):
    """Determines if a Gerrit Change affects any files in relevant paths.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      relevant_paths (Iterable[str]): A collection of paths to be considered
        relevant.
      test_value (bool): The answer to use for testing, or None.
      name (str): The step name to display, defaults to 'path relevance
          check'.

    Returns:
      bool: Whether the given Gerrit Change affects any of the relevant paths.
    """
    with self.m.step.nest(name or 'path relevancy check') as presentation:
      self._ensure_binaries()
      gitiles_commit = gitiles_commit or bbcommon_pb2.GitilesCommit()
      check_request = PointlessBuildCheckRequest(
          gitiles_commit=testplans_proto_bytes(
              serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
                  gitiles_commit)),
          manifest_commit=gitiles_commit.id,
      )

      for source_path in relevant_paths:
        relevant_path = check_request.relevant_paths.add()
        relevant_path.path = source_path

      for gc in gerrit_changes:
        new_gc = check_request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))

      messages_path = self.m.path.mkdtemp(prefix='pointless-build-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      presentation.logs['relevance_input'] = [str(check_request)]
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
      # None is the same as False, for all of the default values.
      test_resp.build_is_pointless.value = not test_value
      test_data = test_resp.SerializeToString()
      response_bin = self.m.file.read_raw('read output file', output_bin_file,
                                          test_data=test_data)
      result = PointlessBuildCheckResponse.FromString(response_bin)

      presentation.logs['relevance_output'] = [str(result)]
      return not bool(result.build_is_pointless.value)

  def is_depgraph_affected(self, gerrit_changes, gitiles_commit, dep_graph,
                           test_value=None, name=None):
    """Determines if a Gerrit Change affects a given dependency graph.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      dep_graph (chromite.api.DepGraph): The dependency graph to compare the
          Gerrit changes against to test for build relevancy.
      test_value (bool): The answer to use for testing, or None.
      name (str): The step name to display, or None for default.

    Returns:
      bool: Whether the given Gerrit Change affects the given dependency graph.
    """
    # Take the union of the relevant paths for the entire dependency graph
    # and pass it as a flat list of paths.
    relevant_paths = _flatten_depgraph_paths(dep_graph)

    return self._are_paths_affected(gerrit_changes, gitiles_commit,
                                    relevant_paths, test_value=test_value,
                                    name=(name or 'depgraph relevance check'))

  def check_for_toolchain_change(self, gerrit_changes, gitiles_commit, chroot,
                                 test_value=None, name=None):
    """Check for toolchain changes.

    Args:
      gerrit_changes (list[GerritChange]): The gerrit changes for the build.
      gitiles_commit (GitilesCommit): The gitiles commit for the build.
      chroot (Chroot): The SDK for the build.
      test_value (bool): The answer to use for testing, or None.
      name (str): The step name to display, or None for default.

    Returns:
      (bool): Whether there are toolchain_cls applied.
    """
    # If there are no Gerrit changes, then the toolchain hasn't changed.
    if not gerrit_changes:
      return False

    with self.m.step.nest(name or 'determine toolchain paths'):
      toolchain_paths_response = \
        self.m.cros_build_api.DependencyService.GetToolchainPaths(
          GetToolchainPathsRequest(chroot=chroot))

    self._toolchain_cls_applied |= self._are_paths_affected(
        gerrit_changes, gitiles_commit,
        relevant_paths=(x.path for x in toolchain_paths_response.paths),
        test_value=test_value)
    return self._toolchain_cls_applied

  def get_dependency_graph(self, sysroot, chroot, packages=None):
    """Calculates the dependency graph for the build target & SDK

    Args:
      sysroot (Sysroot): The Sysroot being used.
      chroot (chromiumos.Chroot): The chroot it is being run in.
      packages (list[chromiumos.PackageInfo]): The packages for which to
          generate the dependency graph.

    Returns:
      (chromite.api.DepGraph, chromite.api.DepGraph): A tuple of opaque
          dependency graph objects, with the first element being the dependency
          graph for the target and the second element the graph for the
          SDK/chroot.
    """
    _dep_graph = namedtuple('_dep_graph', ['target', 'sdk'])
    with self.m.step.nest('dependency graph calculation'):
      # TODO(crbug/1081828): drop build_target once no longer needed by bisect
      # builders, after 2020-11-30.
      build_target = None if not sysroot else sysroot.build_target
      resp = self.m.cros_build_api.DependencyService.GetBuildDependencyGraph(
          GetBuildDependencyGraphRequest(sysroot=sysroot,
                                         build_target=build_target,
                                         chroot=chroot, packages=packages))
      return _dep_graph(target=resp.dep_graph, sdk=resp.sdk_dep_graph)

  def _ensure_binaries(self):
    """Ensure this module's binaries are installed."""
    if not self._pointless_build_checker_path:
      with self.m.step.nest('ensure binaries'):
        with self.m.context(infra_steps=True):
          cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

          pkgs = self.m.cipd.EnsureFile()
          pkgs.add_package('chromiumos/infra/test_planner', 'latest')
          self.m.cipd.ensure(cipd_dir, pkgs)

          self._pointless_build_checker_path = (
              cipd_dir.join('pointless_build_checker'))
          self._build_planner_path = cipd_dir.join('build_plan_generator')


def _flatten_depgraph_paths(depgraph):
  """Returns the union of relevant paths of all packages in the depgraph.

  Args:
    depgraph (chromite.api.DepGraph)

  Returns:
    Set[str]: The union of the 'dependency_source_paths' fields for all
      packages in the depgraph.
  """
  paths = set()
  for package in depgraph.package_deps:
    for source_path in package.dependency_source_paths:
      paths.add(source_path.path)
  return paths
