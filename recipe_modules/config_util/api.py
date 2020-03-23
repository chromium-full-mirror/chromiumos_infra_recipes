# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import json

from google.protobuf import json_format as json_pb

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def ConvertPB(inpb, typ):
  """Convert |inpb| to |typ|."""
  outpb = typ()
  outpb.ParseFromString(inpb.SerializeToString())
  return outpb


class ConfigUtilApi(recipe_api.RecipeApi):
  """A module for handling builder configuration."""

  def initialize(self):
    self._gitiles_commit = None
    self._gerrit_changes = []

  @property
  def gitiles_commit(self):
    return self._gitiles_commit

  @property
  def gerrit_changes(self):
    return self._gerrit_changes

  @property
  def config(self):
    """Return the config for this builder.

    This convenience property wraps cros_infra_config.get_builder_config,
    which caches the data.

    Returns:
      BuilderConfig for this builder.
    """
    return self.m.cros_infra_config.get_builder_config(
        self.m.buildbucket.build.builder.builder, missing_ok=True)

  @property
  def fresh_config(self):
    """Return a freshly loaded config for this builder.

    Returns:
      BuilderConfig for this builder, freshly reloaded.
    """
    # Have cros_infra_config reload its configs.
    self.m.cros_infra_config.force_reload()
    # Now we can just return self.config.
    return self.config

  def _determine_repo_state(self, config, commit, changes):
    """Set _gitiles_commit and _gerrit_changes.

    If the commit and/or changes are other than what was given, that is added as
    an output property in a nested step.

    Args:
      config (BuilderConfig): The builder config, or None.
      commit (GitilesCommit): The gitiles commit to use.  Default:
          common_pb2.GitilesCommit(.... ref='refs/heads/snapshot').
      changes: (GerritChanges): The gerrit changes to apply.  Default: [].
    """
    if not commit or not commit.project:
      # No gitiles_commit: we were (likely) launched directly by either
      # luci-scheduler (no changes), luci-cq (changes), or a user.
      if not changes and config:
        # If there were also no changes, then use the hardcoded default from the
        # configuration.
        changes = [
            ConvertPB(x, common_pb2.GerritChange)
            for x in config.orchestrator.gerrit_changes
        ]

      # Use the default gitiles_commit from the config.
      commit = None if not config else ConvertPB(
          config.orchestrator.gitiles_commit, common_pb2.GitilesCommit)
      # Which may not be there.  In that case, use refs/heads/snapshot.
      if not commit or not commit.project:
        commit = common_pb2.GitilesCommit(
            host='chrome-internal.googlesource.com',
            project='chromeos/manifest-internal', ref='refs/heads/snapshot')
      # We will need commit.id later.  Add it if necessary.
      if not commit.id:
        commit = common_pb2.GitilesCommit(
            host=commit.host, project=commit.project,
            ref=commit.ref, id=self.m.gitiles.fetch_revision(
                commit.host, commit.project, commit.ref))

      # Log what we chose to use (rather than what we were given.)
      step = self.m.step('repo state', cmd=None)
      step.presentation.properties['commit'] = json_pb.MessageToDict(commit)
      step.presentation.properties['changes'] = json.dumps(
          [json_pb.MessageToDict(x) for x in changes])

    # When there is a commit, commit and changes are used unchanged.

    # Record the decision for later.
    self._gitiles_commit = commit
    self._gerrit_changes = changes or []

  def configure_builder(self, commit=None, changes=None,
                        name='configure builder'):
    """Configure the builder.

    Fetch the builder config.
    Determine the actual commit and changes to use.
    Set the bisect_builder and use_flags.

    Args:
      commit (GitilesCommit): The gitiles commit to use.  Default:
          common_pb2.GitilesCommit(.... ref='refs/heads/snapshot').
      changes: (GerritChanges): The gerrit changes to apply.  Default: [].
      name (string): Step name.  Default: "configure builder".

    Returns:
      BuilderConfig
    """
    with self.m.step.nest(name) as presentation:
      config = self.config
      if not config:
        presentation.step_text = 'config not found, assuming deleted'
        return None
      presentation.logs['builder config'] = [str(config)]
      self.m.easy.set_property_step('builder_config',
                                    json_pb.MessageToDict(config))

      parent = [
          x.value
          for x in self.m.buildbucket.build.tags
          if x.key == 'parent_buildbucket_id'
      ]
      if parent:
        presentation.links['parent link'] = (
            self.m.buildbucket.build_url(build_id=parent[0]))

      # TODO(crbug/1053073): once changes is being stripped by callers, we can
      # drop the check of apply_gerrit_changes.
      # For now, we need to handle this here.
      if not config.build.apply_gerrit_changes:
        changes = []

      self._determine_repo_state(config, commit, changes)

    return config
