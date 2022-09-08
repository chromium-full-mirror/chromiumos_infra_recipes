# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import contextlib

from recipe_engine import recipe_api


class WorkspaceUtilApi(recipe_api.RecipeApi):
  """A module workspace setup and manipulation."""

  def __init__(self, properties, *args, **kwargs):
    super(WorkspaceUtilApi, self).__init__(*args, **kwargs)
    self._keep_all_changes = properties.keep_all_changes

  def initialize(self):
    self._patch_sets = []
    # Changes applied in apply_changes().
    self._applied_changes = []
    # Changes that have been checked for toolchain effects.
    self.checked_changes = []

  @property
  def patch_sets(self):
    """The patch sets (with commit and file info) applied to the build."""
    return self._patch_sets

  @property
  def toolchain_cls_applied(self):
    """Whether there are toolchain CLs applied to the source tree."""
    return self.m.cros_relevance.toolchain_cls_applied

  @property
  def workspace_path(self):
    return self.m.src_state.workspace_path

  @contextlib.contextmanager
  def setup_workspace(self, default_main=False):
    """Prepare the source checkout for building.

    Args:
      default_main (bool): Whether to checkout tip-of-tree instead of snapshot
        when no gitiles_commit was provided.

    Returns:
      A context where source is set up, and the current working directory is the
      workspace path.  Note that api.cros_source.cleanup_context() is generally
      going to be needed.
    """
    if not self.m.cros_infra_config.is_configured:
      self.m.cros_source.configure_builder(default_main=default_main)
    with self.m.cros_source.checkout_overlays_context(snapshot_mount=True):
      yield

  @contextlib.contextmanager
  def sync_to_commit(self, commit=None, staging=False, projects=None):
    """Sync the source tree.

    This context manager syncs the workspace path.

    Args:
      commit (GitilesCommit): The gitiles_commit to sync to.  Default: commit
          saved in cros_infra_config.configure_builder().
      staging (bool): Whether this is a staging build.  Default: False.
      projects (List[str]): Project names or paths to return info for. Defaults
        to all projects.
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    commit = commit or self.m.src_state.gitiles_commit

    manifest_url = self.m.src_state.build_manifest.url
    sync_args = dict(manifest_url=manifest_url, is_staging=staging,
                     gitiles_commit=commit, projects=projects)
    branch = commit.ref.split('/', 2)[-1]
    on_branch = not branch in ('', 'main', 'snapshot', 'staging-snapshot')
    if on_branch:
      sync_args['init_opts'] = dict(manifest_branch=branch)
      sync_args['projects'] = [self.m.src_state.build_manifest.project]

    if on_branch or self.m.src_state.manifest_name != 'internal':
      sync_args['cache_path_override'] = self.m.cros_source.workspace_path

    self.m.cros_source.ensure_synced_cache(**sync_args)

    with self.m.context(cwd=self.m.cros_source.workspace_path):
      self.m.cros_source.sync_checkout(commit, manifest_url, projects=projects)
      yield

  def apply_changes(self, changes=None, name='cherry-pick gerrit changes',
                    ignore_missing_projects=False):
    """Apply gerrit changes.

    Args:
      changes (list[GerritChanges]): Changes to apply.  Default: changelist
          saved in cros_infra_config.configure_builder().
      name (string): Step name.  Default: "setup source".
      ignore_missing_projects (bool): If true, changes to projects that are
          not currently checked out (as determined by repo forall) will not be
          applied. An example of when this is useful: it is possible that
          changes includes changes to repos this builder is not allowed to read
          (e.g. because of Cq-Depend grouping); the changes will be discarded
          instead of failing during application.
    """
    changes = self.m.src_state.gerrit_changes if changes is None else changes
    if not changes:
      return

    with self.m.step.nest(name):
      patch_sets = self.m.cros_source.apply_gerrit_changes(
          changes, include_files=True,
          ignore_missing_projects=ignore_missing_projects)
      self._applied_changes.extend(
          patch_set.to_gerrit_change_proto() for patch_set in patch_sets)
      self._patch_sets.extend(patch_sets)
      if not self._keep_all_changes:
        self.m.src_state.gerrit_changes = self._applied_changes

  def checkout_change(self, change=None, name='checkout gerrit change'):
    """Check out a gerrit change using the gerrit refs/changes/... workflow.

      Differs from apply_changes in that the change is directly checked out,
      not cherry picked (so the patchset parent will be accurate). Used for
      things like tricium where line number matters.

    Args:
      change (GerritChange): Change to check out.
      name (string): Step name.  Default: "checkout gerrit change".
    """
    if not change:
      return

    with self.m.step.nest(name):
      self.m.cros_source.checkout_gerrit_change(change)

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
  def sync_to_manifest_groups(self, manifest_groups, local_manifests=None,
                              cache_path_override=None, gitiles_commit=None,
                              manifest_branch=None):
    """Returns a context with manifest groups checked out to cwd.

    The subset of repos in the external manifest + local_manifests matching
    manifest_groups are synced. For example, say the external manifest contains
    repos:

      <project path="a" name="a" groups="g1" />
      <project path="b" name="b" groups="g1" />
      <project path="c" name="c" groups="g2" />

    and a local manifest contains repos:

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
      local_manifests (list[repo.LocalManifest]): A list of local manifests to
          add or None if not syncing a local manifest.
      cache_path_override (Path): Path to sync into. If None, the default
          caching of cros_source.ensure_synced_cache is used.
      gitiles_commit (GitilesCommit): The gitiles_commit to sync to.  Default:
          commit saved in cros_infra_config.configure_builder().
      manifest_branch (str): Branch to checkout. See the `--manifest-branch`
          option of `repo init` for details and defaults.
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    init_opts = {
        'groups': manifest_groups,
    }

    manifest_url = self.m.src_state.external_manifest.url

    if local_manifests:
      init_opts['local_manifests'] = local_manifests

    if manifest_branch:
      init_opts['manifest_branch'] = manifest_branch

      # When syncing to a branch with no local manifests specified, assume the
      # full internal manifest is needed.
      #
      # TODO(b/207578928): Remove this once config checkers specify local
      # manifests.
      if not local_manifests:
        manifest_url = self.m.src_state.internal_manifest.url

    with self.m.cros_source.checkout_overlays_context(
        mount_cache=not cache_path_override):
      self.m.cros_source.ensure_synced_cache(
          gitiles_commit=gitiles_commit, manifest_url=manifest_url,
          init_opts=init_opts, cache_path_override=cache_path_override,
          manifest_branch_override=manifest_branch)
      with self.m.context(
          cwd=cache_path_override or self.m.cros_source.cache_path):
        yield
