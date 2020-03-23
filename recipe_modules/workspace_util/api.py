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
      workspace path.  Note that api.cros_source.cleanup_context() is generally
      going to be needed.
    """
    with self.m.cros_source.checkout_overlays_context(), \
        self.m.context(cwd=self.m.cros_source.workspace_path):
      yield

  def sync_to_commit(self, commit=None, staging=False):
    """Sync the source tree.

    Args:
      commit (GitilesCommit): The gitiles_commit to sync to.  Default: commit
          saved in cros_infra_config.configure_builder().
      staging (bool): Whether this is a staging build.  Default: False.
    """
    self.m.cros_source.ensure_synced_cache(is_staging=staging)
    self.m.cros_source.sync_snapshot(commit or
                                     self.m.cros_infra_config.gitiles_commit)

  def apply_changes(self, changes=None, name='cherry-pick gerrit changes',
                    cq_depend_fail_message=False):
    """Apply gerrit changes.

    Args:
      changes (list[GerritChanges]): Changes to apply.  Default: changelist
          saved in cros_infra_config.configure_builder().
      name (string): Step name.  Default: "setup source".
      cq_depend_fail_message (bool): Whether to give Cq-Depend failure
          advisement on failure to apply patch sets. See below for details.
    """
    patch_sets = []
    if not changes:
      changes = self.m.cros_infra_config.gerrit_changes
    if changes:
      with self.m.step.nest(name):
        patch_sets = self.m.gerrit.fetch_patch_sets(changes, include_files=True)
        try:
          self.m.cros_source.apply_gerrit_patch_sets(patch_sets)
        except self.m.step.StepFailure:
          if cq_depend_fail_message:
            # It is possible that changes includes changes to repos
            # this builder is not allowed to read (e.g. if Cq-Depends groups
            # together changes that affect multiple project repos). In this
            # case, apply_gerrit_patch_sets will fail. Catch the failure and
            # report it as a StepFailure (i.e. not an InfraFailure), with a
            # message that may help the submitter.
            #
            # For now just catch all failures of apply_gerrit_patch_sets. If
            # needed, we can add more filters (e.g. on stdout, exact step that
            # failed) for the above case.
            raise self.m.step.StepFailure(
                ("Failed to apply patch sets. This may be "
                 "the result of Cq-Depends that include CLs outside of this "
                 "builder's read ACLs."))
          else:
            raise
    self._patch_sets = patch_sets

  @contextlib.contextmanager
  def sync_to_manifest_groups(self, manifest_groups,
                              local_manifest=None,
                              cache_path_override=None):
    """Returns a context with manifest groups checked out to cwd.

    Note the importance of the `cache_path_override` parameter. For cases
    where the number of repos being synced is much smaller than a full
    checkout it is more efficient to override the default cache. This is because
    the time to delete unused repos (which are present because of caching) is
    much larger than the time to sync the used repos.

    Args:
      manifest_groups (list[str]): List of manifest groups to checkout.
      local_manifest (repo.LocalManifest): Optional local manifest to sync to.
      cache_path_override (Path): Path to sync into. If None, the default
          caching of cros_source.ensure_synced_cache is used.
    """
    init_opts = {
        'groups': manifest_groups,
    }
    manifest_url = self.m.cros_source.INTERNAL_MANIFEST_URL

    # If a local manifest is specified, init with the public manifest and local
    # manifest. Otherwise, init with the private manifest.
    # TODO(crbug.com/1058171): Require local manifests once they are specified
    # in config.
    if local_manifest:
      manifest_url = self.m.cros_source.EXTERNAL_MANIFEST_URL
      init_opts['local_manifest'] = local_manifest

    self.m.cros_source.ensure_synced_cache(
        manifest_url=manifest_url, init_opts=init_opts,
        cache_path_override=cache_path_override)
    with self.m.context(cwd=cache_path_override or
                        self.m.cros_source.cache_path):
      yield
