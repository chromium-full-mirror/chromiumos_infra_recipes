# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
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

import json

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from recipe_engine import recipe_api
from . import common


class SrcStateApi(recipe_api.RecipeApi):
  """Source State related attributes for Chrome OS recipes."""

  def initialize(self):
    self._gitiles_commit = None
    self._gerrit_changes = None
    self._build_manifest = None

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    The cros_source module checks out the Chrome OS source in this directory.
    It will contain the base checkout and any modifications made by the build,
    and is discarded after the build.
    """
    return self.m.path['start_dir'].join(common.WORKSPACE)

  @property
  def internal_manifest(self):
    """Information about internal manifest.

    Provides immutable information about the Chrome OS internal manifest.

    Returns:
      (ManifestProject): information about the internal manifest.
    """
    return common.ManifestProject.by_name('internal', self.workspace_path)

  @property
  def external_manifest(self):
    """Information about external manifest.

    Provides immutable information about the Chrome OS external manifest.

    Returns:
      (ManifestProject): information about the external manifest.
    """
    return common.ManifestProject.by_name('external', self.workspace_path)

  @property
  def build_manifest(self):
    """Information about the manifest for this build.

    Provides information about the manifest for this build. The default is the
    external manifest.

    Returns:
      (ManifestProject): information about the manifest for this build.
    """
    return (self._build_manifest or
            common.ManifestProject.by_name('external', self.workspace_path))

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

  @property
  def gitiles_commit(self):
    """Return the gitiles_commit for this build.

    This is originally the gitiles_commit from buildbucket.  It will be set by
    cros_infra_config.configure_builder if no gitiles_commit was provided by
    buildbucket.

    Returns:
      (GitilesCommit): the gerrit changes for this build.
    """
    return self._gitiles_commit or self.m.buildbucket.gitiles_commit

  @gitiles_commit.setter
  def gitiles_commit(self, gitiles_commit):
    """Set the gitiles_commit that will be used for the build.

    Args:
      gitiles_commit (GitilesCommit): The value to use.
    """
    if gitiles_commit != self._gitiles_commit:
      with self.m.step.nest('update src_state.gitiles_commit'):
        step = self.m.step('set gitiles_commit', cmd=None)
        step.presentation.properties['commit'] = MessageToDict(gitiles_commit or
                                                               GitilesCommit())
        self._gitiles_commit = gitiles_commit

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
        step.presentation.properties['changes'] = json.dumps(
            '' if gerrit_changes is None else
            [MessageToDict(x) for x in gerrit_changes])
        self._gerrit_changes = gerrit_changes
