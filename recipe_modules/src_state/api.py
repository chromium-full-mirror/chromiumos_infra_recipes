# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing frequently needed values, that we sometimes override.

If you are using cros_source or cros_infra_config, this module is relevant to
your interests.

There are two classes of properties in this module.

1. Constant(ish) things that need a common home to avoid duplication, such as
   workspace_path, internal_manifest, and external_manifest.

2. Information obtained from recipe_engine, which we frequently change:
  - gitiles_commit: Especially when buildbucket does not give us one, we need to
    set it to the correct value for the build.  That varies based on
    builder_config, and other things.

  - gerrit_changes: some builders add changes to the build, and others ignore
    the changes completely.
"""

from google.protobuf.json_format import MessageToJson

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.src_state import common


class SrcStateApi(recipe_api.RecipeApi):
  """Source State related attributes for CrOS recipes."""

  ManifestProject = common.ManifestProject

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.properties = properties

  def initialize(self):
    self._gitiles_commit = None
    self._gerrit_changes = None
    self._build_manifest = None

  @property
  def default_ref(self):
    """The default ref for CrOS repos"""
    return common.default_ref

  @property
  def default_branch(self):
    """The default branch for CrOS repos"""
    return common.default_branch

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    The cros_source module checks out the CrOS source in this directory.
    It will contain the base checkout and any modifications made by the build,
    and is discarded after the build.
    """
    return self.m.path.cleanup_dir.join(common.WORKSPACE)

  @property
  def manifest_name(self):
    """Return the name of the manifest."""
    return ('external'
            if self.build_manifest == self.external_manifest else 'internal')

  @property
  def manifest_projects(self):
    """Return the manifest project names."""
    return [self.internal_manifest.project, self.external_manifest.project]

  @property
  def internal_manifest(self):
    """Information about internal manifest.

    Provides immutable information about the CrOS internal manifest.

    Returns:
      (ManifestProject): information about the internal manifest.
    """
    return common.ManifestProject.by_name('internal', self.workspace_path)

  @property
  def external_manifest(self):
    """Information about external manifest.

    Provides immutable information about the CrOS external manifest.

    Returns:
      (ManifestProject): information about the external manifest.
    """
    return common.ManifestProject.by_name('external', self.workspace_path)

  @property
  def build_manifest(self):
    """Information about the manifest for this build.

    Provides information about the manifest for this build. The default is the
    internal manifest.

    Returns:
      (ManifestProject): information about the manifest for this build.
    """
    return (self._build_manifest or common.ManifestProject.by_gitiles_commit(
        self.gitiles_commit, self.workspace_path))

  @build_manifest.setter
  def build_manifest(self, build_manifest):
    """Set the manifest that will be used for the build.

    Sets the manifest used by this builder.

    Args:
      (ManifestProject): information about the manifest for this build.
    """
    if build_manifest != self._build_manifest:
      with self.m.step.nest('update src_state.build_manifest'):
        self._build_manifest = build_manifest

  def gitiles_commit_to_manifest(self, gitiles_commit):
    """Return the manifest corresponding to the gitiles_commit.

    Args:
      gitiles_commit (GitilesCommit): The gitiles_commit.

    Returns:
      (ManifestProject): Information about the corresponding manifest, or None.
    """
    for manifest in (self.build_manifest, self.external_manifest,
                     self.internal_manifest):
      if gitiles_commit in manifest:
        return manifest
    return None

  @property
  def gitiles_commit(self):
    """Return the gitiles_commit for this build.

    This is originally the gitiles_commit from buildbucket.  It will be set by
    cros_infra_config.configure_builder if no gitiles_commit was provided by
    buildbucket.

    Returns:
      (GitilesCommit): the gerrit changes for this build.
    """
    ret = GitilesCommit()
    ret.CopyFrom(self._gitiles_commit or self.m.buildbucket.gitiles_commit)
    return ret

  @gitiles_commit.setter
  def gitiles_commit(self, gitiles_commit):
    """Set the gitiles_commit that will be used for the build.

    Args:
      gitiles_commit (GitilesCommit): The value to use.
    """
    if gitiles_commit != self._gitiles_commit:
      with self.m.step.nest('update src_state.gitiles_commit'):
        step = self.m.step('set gitiles_commit', cmd=None)
        step.presentation.properties['commit'] = MessageToJson(gitiles_commit or
                                                               GitilesCommit())
        if gitiles_commit is None:
          self._gitiles_commit = None
        else:
          self._gitiles_commit = GitilesCommit()
          self._gitiles_commit.CopyFrom(gitiles_commit or GitilesCommit())
        if (gitiles_commit and gitiles_commit.host and
            gitiles_commit.project and gitiles_commit.ref and
            gitiles_commit.id):
          self.m.buildbucket.set_output_gitiles_commit(self._gitiles_commit)

  @property
  def gerrit_changes(self):
    """Gerrit_changes for this build.

    This is originally the gerrit_changes from buildbucket.  It will be set by
    cros_infra_config.configure_builder if the builder_config overrides or
    augments the list.

    Returns:
      list(GerritChange): the gerrit changes for this build.
    """
    return (self.m.buildbucket.build.input.gerrit_changes
            if self._gerrit_changes is None else self._gerrit_changes)

  @gerrit_changes.setter
  def gerrit_changes(self, gerrit_changes):
    """Set the gerrit_changes that will be used for the build.

    Args:
      gerrit_changes (list[GerritChanges]): The gerrit_changes.
    """
    if ((self._gerrit_changes is None and gerrit_changes is not None) or
        list(self.gerrit_changes) != gerrit_changes):
      with self.m.step.nest('update src_state.gerrit_changes'):
        step = self.m.step('set gerrit_changes', cmd=None)
        step.presentation.properties['changes'] = (
            '' if gerrit_changes is None else
            [MessageToJson(x) for x in gerrit_changes])
        self._gerrit_changes = gerrit_changes
