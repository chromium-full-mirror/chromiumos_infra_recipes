# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api.depgraph import GetBuildDependencyGraphRequest
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

  def are_all_image_builders_pointless(
      self, gerrit_changes, gitiles_commit, name=None):
    """Determines if all image builders can be terminated early.

    Image builders are those that run the build_target recipe, producing an
    IMAGE_ZIP Chrome OS artifact.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      name (str): The step name.

    Returns:
      bool: Whether the normal, image builders can be terminated early.
    """
    return self.is_build_pointless(gerrit_changes, gitiles_commit,
                                   build_target=None, name=name)

  def is_build_pointless(
      self, gerrit_changes, gitiles_commit, build_target, name=None):
    """Determines if build(s) can be terminated early.

    If build_target is set, then the chromiumos workspace must have been
    checked out prior to calling this method. This is a requirement for
    BuildDependencyGraph checks.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      build_target (chromiumos.BuildTarget): The BuildTarget being built.
      name (str): The step name.

    Returns:
      bool: Whether the build can be terminated early.
    """
    with self.m.step.nest(name or 'pointless build check') as step_result:
      dep_graph = None
      if build_target:
        resp = self.m.cros_build_api.DependencyService.GetBuildDependencyGraph(
            GetBuildDependencyGraphRequest(
                build_target=build_target,
            ))
        dep_graph = resp.dep_graph

      self._ensure_pointless_build_checker()
      check_request = PointlessBuildCheckRequest(
        manifest_commit = gitiles_commit.id,
        dep_graph = dep_graph,
      )
      for gc in gerrit_changes:
        new_gc = check_request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))
      cmd = [
          self._pointless_build_checker_path,
          'check-build',
          '--input_json',
          self.m.json.input(jsonpb.MessageToDict(check_request)),
          '--output_json',
          self.m.json.output(),
      ]
      test_plan_res = self.m.step('run check', cmd, infra_step=True)
      output = test_plan_res.json.output
      result = jsonpb.ParseDict(output, PointlessBuildCheckResponse(),
                                ignore_unknown_fields=True)
      step_result.presentation.logs['relevance_output'] = [str(result)]
      if result.build_is_pointless.value:
        step_result.presentation.step_text = (
            'build is irrelevant')
        step_result.presentation.properties['pointless_build'] = True
      else:
        step_result.presentation.step_text = (
            'build is relevant')
      return result.build_is_pointless.value

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
