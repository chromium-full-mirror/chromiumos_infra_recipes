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
    self._commits = []
    # Changes applied in apply_changes().
    self._applied_changes = []
    # Changes that have been checked for toolchain effects.
    self.checked_changes = []

  @property
  def patch_sets(self):
    return [x.patch_set for x in self._commits]

  @property
  def commits(self):
    return self._commits

  @property
  def toolchain_cls_applied(self):
    """Whether there are toolchain CLs applied to the source tree."""
    return self.m.cros_relevance.toolchain_cls_applied

  @property
  def workspace_path(self):
    return self.m.src_state.workspace_path

  @contextlib.contextmanager
  def setup_workspace(self):
    """Prepare the source checkout for building.

    Returns:
      A context where source is set up, and the current working directory is the
      workspace path.  Note that api.cros_source.cleanup_context() is generally
      going to be needed.
    """
    with self.m.cros_source.checkout_overlays_context():
      yield

  @contextlib.contextmanager
  def sync_to_commit(self, commit=None, staging=False):
    """Sync the source tree.

    This context manager syncs the workspace path.

    Args:
      commit (GitilesCommit): The gitiles_commit to sync to.  Default: commit
          saved in cros_infra_config.configure_builder().
      staging (bool): Whether this is a staging build.  Default: False.
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    commit = commit or self.m.src_state.gitiles_commit

    manifest_url = self.m.src_state.build_manifest.url
    cache_path_override = (
        self.m.cros_source.cache_path
        if self.m.src_state.build_manifest == self.m.src_state.internal_manifest
        else self.m.cros_source.workspace_path)
    self.m.cros_source.ensure_synced_cache(
        manifest_url=manifest_url, is_staging=staging, gitiles_commit=commit,
        cache_path_override=cache_path_override)

    with self.m.context(cwd=self.m.cros_source.workspace_path):
      self.m.cros_source.sync_snapshot(commit, manifest_url)
      yield

  def apply_changes(self, changes=None, name='cherry-pick gerrit changes',
                    fail_not_applicable=False):
    """Apply gerrit changes.

    Args:
      changes (list[GerritChanges]): Changes to apply.  Default: changelist
          saved in cros_infra_config.configure_builder().
      name (string): Step name.  Default: "setup source".
      fail_not_applicable (bool): If true, changes to projects that are
          not currently checked out (as determined by repo forall) will not be
          applied. An example of when this is useful: it is possible that
          changes includes changes to repos this builder is not allowed to read
          (e.g. because of Cq-Depend grouping); the changes will be discarded
          instead of failing during application.
    """
    patch_sets = []
    changes = self.m.src_state.gerrit_changes if changes is None else changes
    if not changes:
      return

    # Only try to apply changes once.
    discarded_change_numbers = [
        str(c.change) for c in changes if c in self._applied_changes
    ]
    changes = [c for c in changes if c not in self._applied_changes]

    with self.m.step.nest(name) as presentation:
      if fail_not_applicable:
        synced_projects = [p.name for p in self.m.repo.project_infos()]

        discarded_change_numbers.extend([
            str(c.change) for c in changes if c.project not in synced_projects
        ])
        changes = [c for c in changes if c.project in synced_projects]

      if discarded_change_numbers:
        presentation.step_text = 'Discarded changes: {}'.format(
            ', '.join(discarded_change_numbers))

      commits = self.m.cros_source.apply_gerrit_changes(changes,
                                                        include_files=True)
      self._commits.extend(commits)
      self._applied_changes.extend(changes)

  def detect_toolchain_cls(self, chroot, gitiles_commit=None,
                           gerrit_changes=None, test_value=None, name=None):
    """Check for toolchain changes.

    If there are any changes that affect the toolchain, set that workspace
    attribute.

    Args:
      gitiles_commit (GitilesCommit): The gitiles commit to use, or none to use
          the value from config.
      gerrit_changes (list[GerritChange]): The gerrit changes in use, None to
          use the changes already applied via apply_changes().
      chroot (Chroot): The chroot for the build.
      name (str): The name for the step, or None for default.
      test_value (bool): The value to use for tests.  Default: No toolchain
          changes detected unless step data is provided elsewhere.

    Returns:
      (bool) whether there are toolchain patches applied.
    """
    gitiles_commit = gitiles_commit or self.m.src_state.gitiles_commit
    gerrit_changes = gerrit_changes or self._applied_changes

    # See if there are any new changes to check.
    to_check = [c for c in gerrit_changes if not c in self.checked_changes]
    if not to_check:
      return self.toolchain_cls_applied

    with self.m.step.nest(name or 'detect toolchain change') as detect:
      changed = self.m.cros_relevance.check_for_toolchain_change(
          gitiles_commit=gitiles_commit, gerrit_changes=gerrit_changes,
          chroot=chroot, test_value=test_value)
      self.checked_changes.extend(to_check)
      self.m.easy.set_properties_step(testing_toolchain=changed)
      detect.step_text = 'change detected' if changed else 'no change'
      return changed

  @contextlib.contextmanager
  def sync_to_manifest_groups(self, manifest_groups, local_manifest=None,
                              cache_path_override=None, gitiles_commit=None):
    """Returns a context with manifest groups checked out to cwd.

    The subset of repos in the external manifest + local_manifest matching
    manifest_groups are synced. For example, say the external manifest contains
    repos:

      <project path="a" name="a" groups="g1" />
      <project path="b" name="b" groups="g1" />
      <project path="c" name="c" groups="g2" />

    and the local manifest contains repos:

      <project path="d" name="d" groups="g3" />
      <project path="e" name="e" groups="g4" />

    and manifest_groups is ["g1", "g4"]. Repos "a", "b", and "e" will be synced.

    Note the importance of the `cache_path_override` parameter. For cases
    where the number of repos being synced is much smaller than a full
    checkout it is more efficient to override the default cache. This is because
    the time to delete unused repos (which are present because of caching) is
    much larger than the time to sync the used repos.

    Args:
      manifest_groups (list[str]): List of manifest groups to checkout.
      local_manifest (repo.LocalManifest): Local manifest to add or None if not
          syncing a local manifest.
      cache_path_override (Path): Path to sync into. If None, the default
          caching of cros_source.ensure_synced_cache is used.
      gitiles_commit (GitilesCommit): The gitiles_commit to sync to.  Default:
          commit saved in cros_infra_config.configure_builder().
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    init_opts = {
        'groups': manifest_groups,
    }
    if local_manifest:
      init_opts['local_manifest'] = local_manifest

    self.m.cros_source.ensure_synced_cache(
        gitiles_commit=gitiles_commit,
        manifest_url=self.m.src_state.external_manifest.url,
        init_opts=init_opts, cache_path_override=cache_path_override)
    with self.m.context(
        cwd=cache_path_override or self.m.cros_source.cache_path):
      yield
