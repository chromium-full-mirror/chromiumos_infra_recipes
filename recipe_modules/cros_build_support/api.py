# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import contextlib

from google.protobuf import json_format as json_pb

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

class CrosBuildSupportApi(recipe_api.RecipeApi):
  """A module to support building."""

  def initialize(self):
    self._patch_sets = []
    self._gitiles_commit = None
    self._gerrit_changes = []

  @property
  def gitiles_commit(self):
    return self._gitiles_commit

  @property
  def gerrit_changes(self):
    return self._gerrit_changes

  @property
  def patch_sets(self):
    return self._patch_sets

  def configure_builder(self, build_target=None, commit=None, changes=None,
                        name='configure builder'):
    """Configure the builder.

    Args:
      build_target (BuildTarget): The build target.  Default: None.
      commit (GitilesCommit): The gitiles commit to use.  Default:
          common_pb2.GitilesCommit(.... ref='refs/heads/snapshot').
      changes: (GerritChanges): The gerrit changes to apply.  Default: [].
      name (string): Step name.  Default: "configure builder".

    Returns:
      BuilderConfig
    """
    with self.m.step.nest(name) as step:
      try:
        config = self.m.cros_infra_config.get_builder_config(
            self.m.buildbucket.build.builder.builder)
      except LookupError:
        step.step_text = 'config not found, assuming deleted'
        return None
      step.logs['builder config'] = [str(config)]
      step.properties['builder_config'] = json_pb.MessageToDict(config)

      parent = [x.value
                for x in self.m.buildbucket.build.tags
                if x.key == 'parent_buildbucket_id']
      if parent:
        step.links['parent link'] = 'https://ci.chromium.org/b/%s' % parent[0]

      # TODO(crbug/1053073): once changes is being stripped by callers, we can
      # drop the check of apply_gerrit_changes.
      # For now, we need to handle this here.
      if not config.build.apply_gerrit_changes:
        changes = []
      self._gitiles_commit = commit
      self._gerrit_changes = changes or []

    if build_target:
      self.m.cros_bisect.set_bisect_builder(build_target.name)
    self.m.cros_sdk.set_use_flags(config.build.use_flags)

    return config

  @contextlib.contextmanager
  def setup_workspace(self):
    """Prepare the source checkout for building.

    Returns:
      A context where source is set up, and the current working directory is the
          workspace path.
    """
    with self.m.cros_source.checkout_overlays_context(), \
        self.m.cros_sdk.cleanup_context(
            checkout_path=self.m.cros_source.workspace_path), \
        self.m.context(cwd=self.m.cros_source.workspace_path):
      yield

  def sync_to_commit(self, commit=None, staging=False):
    """Sync the source tree.

    Args:
      commit (GitilesCommit): The gitiles_commit to sync to.  Default: commit
          saved in configure_builder()
      staging (bool): Whether this is a staging build.  Default: False.
    """
    self.m.cros_source.ensure_synced_cache(is_staging=staging)
    self.m.cros_source.sync_snapshot(commit or self.gitiles_commit)

  def apply_changes(self, changes=None, name='cherry-pick gerrit changes'):
    """Apply gerrit changes.

    Args:
      changes (list[GerritChanges]): Changes to apply.  Default: changelist
          saved in configure_builder()
      name (string): Step name.  Default: "setup source".
    """
    patch_sets = []
    if not changes:
      changes = self.gerrit_changes
    if changes:
      with self.m.step.nest(name):
        patch_sets = self.m.gerrit.fetch_patch_sets(changes, include_files=True)
        self.m.cros_source.apply_gerrit_patch_sets(patch_sets)
    self._patch_sets = patch_sets
