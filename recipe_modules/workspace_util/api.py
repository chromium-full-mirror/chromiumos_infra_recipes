# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import contextlib
import json

from google.protobuf import json_format as json_pb

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class WorkspaceUtilApi(recipe_api.RecipeApi):
  """A module workspace setup and manipulation."""

  def initialize(self):
    self._patch_sets = []

  @property
  def patch_sets(self):
    return self._patch_sets

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
          saved in config_util.configure_builder().
      staging (bool): Whether this is a staging build.  Default: False.
    """
    self.m.cros_source.ensure_synced_cache(is_staging=staging)
    self.m.cros_source.sync_snapshot(commit or
                                     self.m.config_util.gitiles_commit)

  def apply_changes(self, changes=None, name='cherry-pick gerrit changes'):
    """Apply gerrit changes.

    Args:
      changes (list[GerritChanges]): Changes to apply.  Default: changelist
          saved in config_util.configure_builder().
      name (string): Step name.  Default: "setup source".
    """
    patch_sets = []
    if not changes:
      changes = self.m.config_util.gerrit_changes
    if changes:
      with self.m.step.nest(name):
        patch_sets = self.m.gerrit.fetch_patch_sets(changes, include_files=True)
        self.m.cros_source.apply_gerrit_patch_sets(patch_sets)
    self._patch_sets = patch_sets
