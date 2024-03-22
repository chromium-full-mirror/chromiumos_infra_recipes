# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import contextlib
from typing import Any, Dict, Generator, List, Optional

from PB.chromiumos.common import Chroot
from PB.chromite.api.depgraph import GetToolchainPathsRequest
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.testplans.pointless_build import PointlessBuildCheckRequest
from PB.recipe_modules.chromeos.workspace_util.workspace_util import \
    WorkspaceUtilProperties
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.repo.api import LocalManifest

from recipe_engine import recipe_api
from recipe_engine.config_types import Path


class WorkspaceUtilApi(recipe_api.RecipeApi):
  """A module workspace setup and manipulation."""

  def __init__(self, properties: WorkspaceUtilProperties, *args: Any,
               **kwargs: Any) -> None:
    super().__init__(*args, **kwargs)
    self._keep_all_changes = properties.keep_all_changes
    self._patch_sets: List[PatchSet] = []

    # Changes applied in apply_changes().
    self._applied_changes: List[GerritChange] = []

    # Changes that have been checked for toolchain effects.
    self.checked_changes: List[GerritChange] = []

  @property
  def patch_sets(self) -> List[PatchSet]:
    """The patch sets (with commit and file info) applied to the build."""
    return self._patch_sets

  @property
  def toolchain_cls_applied(self) -> bool:
    """Whether there are toolchain CLs applied to the source tree."""
    return self.m.cros_relevance.toolchain_cls_applied

  @property
  def workspace_path(self) -> Path:
    return self.m.src_state.workspace_path

  @contextlib.contextmanager
  def setup_workspace(self, default_main: bool = False) -> Generator:
    """Prepare the source checkout for building.

    Args:
      default_main: Whether to checkout tip-of-tree instead of snapshot when no
        gitiles_commit was provided.

    Yields:
      A context where source is set up, and the current working directory is
      the workspace path. Note that api.cros_sdk.cleanup_context() is
      generally going to be needed.
    """
    if not self.m.cros_infra_config.is_configured:
      self.m.cros_source.configure_builder(default_main=default_main)
    with self.m.cros_source.checkout_overlays_context():
      yield

  @contextlib.contextmanager
  def sync_to_commit(self, commit: Optional[GitilesCommit] = None,
                     staging: bool = False,
                     projects: Optional[List[str]] = None) -> Generator:
    """Sync the source tree.

    Args:
      commit: The gitiles_commit to sync to. Default: commit saved in
        cros_infra_config.configure_builder().
      staging: Whether this is a staging build.
      projects: Project names or paths to return info for. Defaults to all
        projects.

    Yields:
      A context manager which syncs the workspace path.
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    commit = commit or self.m.src_state.gitiles_commit
    manifest_url = self.m.src_state.build_manifest.url
    init_opts = {}

    branch = commit.ref.split('/', 2)[-1]
    on_branch = branch not in ('', 'main', 'snapshot', 'staging-snapshot')
    if on_branch:
      init_opts['manifest_branch'] = branch
      ensure_synced_cache_projects = [self.m.src_state.build_manifest.project]
    else:
      ensure_synced_cache_projects = projects

    if on_branch or self.m.src_state.manifest_name != 'internal':
      cache_path_override = self.m.cros_source.workspace_path
    else:
      cache_path_override = None

    self.m.cros_source.ensure_synced_cache(
        manifest_url=manifest_url,
        is_staging=staging,
        gitiles_commit=commit,
        projects=ensure_synced_cache_projects,
        cache_path_override=cache_path_override,
        init_opts=init_opts,
    )

    with self.m.context(cwd=self.m.cros_source.workspace_path):
      self.m.cros_source.sync_checkout(commit, manifest_url, projects=projects)
      yield

  def apply_changes(self, changes: Optional[List[GerritChange]] = None,
                    name: str = 'cherry-pick gerrit changes',
                    ignore_missing_projects: bool = False) -> None:
    """Apply gerrit changes.

    Args:
      changes: Changes to apply. Default: changelist saved in
        cros_infra_config.configure_builder().
      name: Step name.
      ignore_missing_projects: If true, changes to projects that are not
        currently checked out (as determined by repo forall) will not be
        applied. An example of when this is useful: it is possible that changes
        includes changes to repos this builder is not allowed to read (e.g.
        because of Cq-Depend grouping); the changes will be discarded instead
        of failing during application.
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
      # New changes were applied, so we may have to re-check for toolchain
      # changes. Don't bother if this is already a toolchain CL.
      if not self.toolchain_cls_applied:
        self.m.cros_relevance.toolchain_cls_applied = None


  def checkout_change(self, change: Optional[GerritChange] = None,
                      name: str = 'checkout gerrit change') -> None:
    """Check out a gerrit change using the gerrit refs/changes/... workflow.

    Differs from apply_changes in that the change is directly checked out, not
    cherry picked, so the patchset parent will be accurate. Used for things like
    tricium where line number matters.

    Args:
      change: Change to check out.
      name: Step name.
    """
    if not change:
      return

    with self.m.step.nest(name):
      self.m.cros_source.checkout_gerrit_change(change)

  def detect_toolchain_cls(self, chroot: Chroot,
                           test_value: Optional[bool] = None,
                           name: Optional[str] = None) -> bool:
    """Check for toolchain changes.

    If there are any changes that affect the toolchain, set that workspace
    attribute.

    Args:
      chroot: The chroot for the build.
      test_value: The value to use for tests, or None to detect toolchain
        changes unless step data is provided elsewhere.
      name: The name for the step, or None for default.

    Returns:
      Whether there are toolchain patches applied.
    """

    with self.m.step.nest(name or
                          'detect toolchain change') as step_presentation:
      if self.toolchain_cls_applied is not None:
        step_presentation.step_text = (
            f'using cached value: {self.toolchain_cls_applied}')
        return self.toolchain_cls_applied

      if not self.patch_sets:
        self.m.cros_relevance.toolchain_cls_applied = False
        step_presentation.step_text = 'no changes to check for relevancy'
        return self.toolchain_cls_applied

      toolchain_paths_response = \
        self.m.cros_build_api.DependencyService.GetToolchainPaths(
          GetToolchainPathsRequest(chroot=chroot))
      relevant_paths = (x.path for x in toolchain_paths_response.paths)

      affected_paths = self.m.cros_relevance.get_affected_paths(self.patch_sets)

      check_request = PointlessBuildCheckRequest(
          ignore_known_non_portage_directories=True,
      )
      for source_path in affected_paths:
        affected_path = check_request.affected_paths.add()
        affected_path.path = source_path
      for source_path in relevant_paths:
        relevant_path = check_request.relevant_paths.add()
        relevant_path.path = source_path

      response = self.m.cros_relevance.call_pointless_build_checker(
          check_request, step_presentation, not test_value)

      # If build is pointless then nothing has changed in the toolchain.
      changed = not bool(response.build_is_pointless.value)
      self.m.cros_relevance.toolchain_cls_applied = changed
      self.m.easy.set_properties_step(testing_toolchain=changed)
      step_presentation.step_text = 'change detected' if changed else 'no change'
      return changed

  @contextlib.contextmanager
  def sync_to_manifest_groups(
      self, manifest_groups: List[str],
      local_manifests: Optional[List[LocalManifest]] = None,
      cache_path_override: Optional[Path] = None,
      gitiles_commit: Optional[GitilesCommit] = None,
      manifest_branch: Optional[str] = None) -> Generator:
    """Return a context with manifest groups checked out to cwd.

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
      manifest_groups: List of manifest groups to checkout.
      local_manifests: A list of local manifests to add, or None if not syncing
        a local manifest.
      cache_path_override: Path to sync into. If None, the default caching of
        cros_source.ensure_synced_cache is used.
      gitiles_commit: The gitiles_commit to sync to. Default: commit saved in
        cros_infra_config.configure_builder().
      manifest_branch: Branch to checkout. See the `--manifest-branch` option
        of `repo init` for details and defaults.
    """
    assert self.m.cros_infra_config.is_configured, 'builder not configured'
    init_opts: Dict[str, Any] = {
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
