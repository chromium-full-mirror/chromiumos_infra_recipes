# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from google.protobuf import json_format
from recipe_engine import recipe_api
from recipe_engine.util import exponential_retry

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.test_retry import SuiteRetryCfg

REPO_URL = 'https://chrome-internal.googlesource.com/chromeos/infra/config'


def ConvertPB(inpb, typ):
  """Convert |inpb| to |typ|."""
  outpb = typ()
  outpb.ParseFromString(inpb.SerializeToString())
  return outpb


class CrosInfraConfigApi(recipe_api.RecipeApi):
  """A module for accessing data in the chromeos/infra/config repo"""

  def __init__(self, properties, *args, **kwargs):
    super(CrosInfraConfigApi, self).__init__(*args, **kwargs)
    # Map from BuilderConfig's id.name to BuilderConfig, lazily loaded.
    self._name_to_builder_config = {}

    # Save the properties message.
    self._properties = properties

    # Parse properties.config_ref
    self._config_ref = properties.config_ref or 'master'

    # Gitiles commit and gerrit changes for this builder.
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
    return self.get_builder_config(self.m.buildbucket.build.builder.builder,
                                   missing_ok=True)

  @property
  def fresh_config(self):
    """Return a freshly loaded config for this builder.

    Returns:
      BuilderConfig for this builder, freshly reloaded.
    """
    # Have cros_infra_config reload its configs.
    self.force_reload()
    # Now we can just return self.config.
    return self.config

  @property
  def props_for_child_build(self):
    """Return properties dict meant to be passed to child builds.

    Preserve $chromeos/cros_infra_config when launching a child build.
    """
    if not self._properties.config_ref:
      return {}
    msg = CrosInfraConfigProperties()
    msg.CopyFrom(self._properties)
    return {
        '$chromeos/cros_infra_config':
            json_format.MessageToDict(msg, preserving_proto_field_name=True)
    }

  @exponential_retry(retries=3,
                     condition=lambda e: getattr(e, 'had_timeout', False))
  def _fetch_builder_configs(self):
    """Helper method to fetch the builder configs file.

    Downloads the builder configs file and returns it. This helper function
    allows the retry to target the gitiles download specifically.
    """
    # Step nesting needs to happen here or it shows up many times in Milo,
    # once for each builder.
    return self.m.depot_gitiles.download_file(
        REPO_URL, 'generated/builder_configs.binaryproto',
        branch=self._config_ref,
        step_test_data=self.test_api.builder_configs_step_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)

  def _get_name_to_builder_config(self, force_reload=False):
    """Helper method that returns the name to BuilderConfig map.

    Loads the proto and builds the map if it hasn't already been done.
    """
    if force_reload:
      self._name_to_builder_config.clear()
    if not self._name_to_builder_config:
      name_to_builder_config = {}
      # Step nesting needs to happen here or it shows up many times in Milo,
      # once for each builder.
      with self.m.step.nest('read builder configs'), self.m.context(
          infra_steps=True):
        builder_configs_file = self._fetch_builder_configs()
      configs = BuilderConfigs.FromString(builder_configs_file)
      for config in configs.builder_configs:
        name_to_builder_config[config.id.name] = config
      self._name_to_builder_config = name_to_builder_config
    return self._name_to_builder_config

  def get_builder_config(self, builder_name, missing_ok=False):
    """Gets the BuilderConfig for the specified builder from the master branch.

    Finds the BuilderConfig whose id.name matches the specified Buildbucket
    builder.

    This function loads the checked in proto and forms a map from id.name to
    BuilderConfig on the first call. Subsequent calls just look up in the map,
    so will be much faster than the first call. This is meant for the case when
    many lookups are needed, e.g. a parent builder looks up all child configs.

    Args:
      * builder_name (str): The Buildbucket builder to look for, matched against
        BuilderConfig's id.name.
      * missing_ok (boolean): Whether to allow a missing config.

    Returns:
      A BuilderConfigs proto.

    Raises:
      A LookupError if a BuilderConfig is not found for the specified builder.

    """
    config = self._get_name_to_builder_config().get(builder_name)
    if not config and not missing_ok:
      raise LookupError('No BuilderConfig for builder {}'.format(builder_name))
    return config

  def safe_get_builder_configs(self, builder_names):
    """Gets the BuilderConfigs for the specified builder names from master.

    The returned dict will not contain key/values for builder names that could
    not be found in config.

    Args:
      * builder_names (list[str]): Buildbucket builders to look for, matched
        against BuilderConfig id.name.

    Returns:
      dict(str, BuilderConfig) of found BuilderConfigs.
    """
    builder_configs = {}
    for name in builder_names:
      try:
        builder_configs[name] = self.get_builder_config(name)
      except LookupError:
        # Carry on if the builder doesn't exist anymore.
        pass
    return builder_configs

  def force_reload(self):
    """Force a reload of the config map from ToT."""
    self._get_name_to_builder_config(force_reload=True)

  def should_run(self, run_spec):
    return run_spec in [BuilderConfig.RUN, BuilderConfig.RUN_EXIT]

  def should_exit(self, run_spec):
    return run_spec == BuilderConfig.RUN_EXIT

  def get_bot_policy_config(self):
    """Get BotPolicies as defined in infra/config.

    Returns:
      BotPolicyCfg as defined in the config repo.
    """
    bot_policy_file = self.m.depot_gitiles.download_file(
        REPO_URL, 'bot_scaling/generated/bot_policy.binaryproto',
        step_test_data=self.test_api.bot_policy_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)
    return BotPolicyCfg.FromString(bot_policy_file)

  def get_vm_retry_config(self):
    """Get SuiteRetryCfg as defined in infra/config for tast vm.

    Returns:
      SuiteRetryCfg as defined in the config repo.
    """
    vm_retry_config_file = self.m.depot_gitiles.download_file(
        REPO_URL, 'testingconfig/generated/vm_retry.binaryproto',
        step_test_data=self.test_api.vm_retry_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)
    return SuiteRetryCfg.FromString(vm_retry_config_file)

  def get_dut_tracking_config(self):
    """Get TrackingPolicyCfg as defined in infra/config.

    Returns:
      TrackingPolicyCfg as defined in the config repo.
    """
    tracking_policy_file = self.m.depot_gitiles.download_file(
        REPO_URL, 'testingconfig/generated/dut_tracking.binaryproto',
        step_test_data=self.test_api.dut_tracking_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)
    return TrackingPolicyCfg.FromString(tracking_policy_file)

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
    changes = changes or []
    changed = False
    if not commit or not commit.project:
      # No gitiles_commit: we were (likely) launched directly by either
      # luci-scheduler (no changes), luci-cq (changes), or a user.

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
      if commit:
        changed = True

    # If we are not ignoring the changelist in the config then insert any such
    # to the changelist.
    if config and not self._properties.ignore_config_changelist:
      if config.orchestrator.gerrit_changes:
        converted_changes = [
            ConvertPB(x, common_pb2.GerritChange)
            for x in config.orchestrator.gerrit_changes
        ]
        changes = converted_changes + [
            x for x in changes if x not in converted_changes]
        changed = True

    if changed:
      # Log what we chose to use (rather than what we were given.)
      step = self.m.step('repo state', cmd=None)
      step.presentation.properties['commit'] = json_format.MessageToDict(commit)
      step.presentation.properties['changes'] = json.dumps(
          [json_format.MessageToDict(x) for x in changes])

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
      changes (GerritChanges): The gerrit changes to apply.  Default: [].
      name (string): Step name.  Default: "configure builder".

    Returns:
      BuilderConfig or None
    """
    with self.m.step.nest(name) as presentation:
      config = self.config
      if config:
        presentation.logs['builder config'] = [str(config)]
        self.m.easy.set_property_step('builder_config',
                                      json_format.MessageToDict(config))
      else:
        presentation.step_text = 'config not found, assuming deleted'

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
      if (config and config.HasField('build') and
          not config.build.apply_gerrit_changes):
        changes = []

      self._determine_repo_state(config, commit, changes)

    return config
