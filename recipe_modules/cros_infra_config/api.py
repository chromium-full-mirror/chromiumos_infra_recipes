# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToDict, Parse, ParseDict
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.util.util import exponential_retry

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import UseFlag
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.go.chromium.org.luci.buildbucket.proto.common import (GerritChange,
                                                              GitilesCommit)
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.testplans.test_retry import SuiteRetryCfg

CHROME_OS_REPO_URL = (
    'https://chrome-internal.googlesource.com/chromeos/infra/config')
CHROME_REPO_URL = 'https://chrome-internal.googlesource.com/infradata/config'


def ConvertPB(inpb, typ):
  """Convert |inpb| to |typ|."""
  outpb = typ()
  outpb.ParseFromString(inpb.SerializeToString())
  return outpb


class CrosInfraConfigApi(recipe_api.RecipeApi):
  """A module for accessing data in the chromeos/infra/config repo

  go/robocrop-chrome-browser-proposal: This module is temporarily used to
  access the Chrome Browser infradata/config repo"""

  def __init__(self, properties, *args, **kwargs):
    super(CrosInfraConfigApi, self).__init__(*args, **kwargs)
    # Map from BuilderConfig's id.name to BuilderConfig, lazily loaded.
    self._name_to_builder_config = {}

    # Save the properties message.
    self._properties = properties

    # Parse properties.config_ref
    self._config_ref = properties.config_ref

    # The sha1 of the recipes package from cipd.
    self._package_git_revision = None

    # Is this builder running in the staging bucket?
    self._is_staging = False

    # Is the builder configured?
    self._is_configured = False

  def initialize(self):
    # If the builder is in the staging bucket, or has a name that begins
    # 'staging-', then assume we are in staging.
    builder = self.m.buildbucket.build.builder
    self._is_staging = (
        builder.bucket == 'staging' or builder.builder.startswith('staging-'))
    # Parse properties.config_ref, but only on staging.
    self._config_ref = (
        self._config_ref if self._is_staging and self._config_ref else 'HEAD')

    self._properties.honor_gitiles_commit_ref |= (
        'chromeos.cros_infra_config.honor_gitiles_commit_ref' in
        self.experiments)

    # Hold off on the other fields until they are used, to avoid unnecessary
    # clutter in the expectations files.

  @property
  def is_configured(self):
    return self._is_configured

  @property
  def package_git_revision(self):
    return self._package_git_revision or self._get_package_git_revision()

  @property
  def gitiles_commit(self):
    return self.m.src_state.gitiles_commit

  @property
  def gerrit_changes(self):
    return self.m.src_state.gerrit_changes

  @property
  def experiments(self):
    """Return the list of experiments active for this build."""
    return [
        x.encode('utf-8') for x in self.m.buildbucket.build.input.experiments
    ]

  @property
  def experiments_for_child_build(self):
    """Return value for bb schedule_request experiments arg."""
    return {k: True for k in self.experiments}

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
  def config_or_default(self):
    """Config or default config.

    The default config is empty, except for:
      - id.name = this builder
      - chrome.internal = True
      - build.install_packages.run_spec = RUN
      - build.use_flags = 'chrome_internal'
    """
    return self.config or BuilderConfig(
        id=BuilderConfig.Id(name=self.m.buildbucket.build.builder.builder),
        chrome=BuilderConfig.Chrome(internal=True), build=BuilderConfig.Build(
            install_packages=BuilderConfig.Build.InstallPackages(
                run_spec=BuilderConfig.RUN),
            use_flags=[UseFlag(flag='chrome_internal')]))

  @property
  def is_staging(self):
    return self._is_staging

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
    if not MessageToDict(self._properties):
      return {}
    msg = CrosInfraConfigProperties()
    msg.CopyFrom(self._properties)
    return {
        '$chromeos/cros_infra_config':
            MessageToDict(msg, preserving_proto_field_name=True)
    }

  @property
  def current_builder_group(self):
    """Get the builder group for the currently running builder."""
    return self.m.properties.get('builder_group')

  @property
  def parent_builder_group(self):
    """Get the builder group for the parent builder."""
    return self.m.properties.get('parent_builder_group')

  @property
  def target_builder_group(self):
    """Get the builder group for the target builder.

    This is used by findit, which has a single builder that performs
    bisection using the configuration of another builder.
    """
    return self.m.properties.get('target_builder_group')

  @exponential_retry(retries=3,
                     condition=lambda e: getattr(e, 'had_timeout', False))
  def _download_binproto(self, filename, step_test_data, timeout=None,
                         application='ChromeOS', message=None):
    """Helper method to fetch a file from gititles."""
    repo = CHROME_OS_REPO_URL
    if application == 'Chrome':
      repo = CHROME_REPO_URL

    if self._config_ref.startswith('refs/changes/') and message:
      # If we are running with a CL for the config_ref, convert the jsonpb proto
      # to binaryproto and return that.
      data = self.m.depot_gitiles.download_file(
          repo, filename + '.cfg', branch=self._config_ref,
          step_test_data=step_test_data, timeout=timeout or
          self.test_api.gitiles_timeout_seconds).encode('utf-8')
      return Parse(data, message).SerializeToString()

    return self.m.depot_gitiles.download_file(
        repo, filename + '.binaryproto', branch=self._config_ref,
        step_test_data=step_test_data, timeout=timeout or
        self.test_api.gitiles_timeout_seconds)

  def _fetch_builder_configs(self):
    """Helper method to fetch the builder configs file.

    Downloads the builder configs file and returns it. This helper function
    allows the retry to target the gitiles download specifically.
    """
    # Step nesting needs to happen here or it shows up many times in Milo,
    # once for each builder.
    return self._download_binproto('generated/builder_configs',
                                   self.test_api.builder_configs_step_test_data,
                                   message=BuilderConfigs())

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
    """Gets the BuilderConfig for the specified builder from HEAD.

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
    """Gets the BuilderConfigs for the specified builder names from HEAD.

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

  def get_bot_policy_config(self, application='ChromeOS'):
    """Get BotPolicies as defined in infra/config.
    If application is Chrome, BotPolicies will be fetched from infradata/config.

    Returns:
      BotPolicyCfg as defined in the config repo.
    """
    if application == 'Chrome':
      return BotPolicyCfg.FromString(
          self._download_binproto('configs/bot-scaling/generated/bot_policy',
                                  self.test_api.bot_policy_test_data_chrome,
                                  application='Chrome', message=BotPolicyCfg()))
    return BotPolicyCfg.FromString(
        self._download_binproto('bot_scaling/generated/bot_policy',
                                self.test_api.bot_policy_test_data,
                                message=BotPolicyCfg()))

  def get_vm_retry_config(self):
    """Get SuiteRetryCfg as defined in infra/config for tast vm.

    Returns:
      SuiteRetryCfg as defined in the config repo.
    """
    return SuiteRetryCfg.FromString(
        self._download_binproto('testingconfig/generated/vm_retry',
                                self.test_api.vm_retry_test_data,
                                message=SuiteRetryCfg()))

  def get_dut_tracking_config(self):
    """Get TrackingPolicyCfg as defined in infra/config.

    Returns:
      TrackingPolicyCfg as defined in the config repo.
    """
    return TrackingPolicyCfg.FromString(
        self._download_binproto('testingconfig/generated/dut_tracking',
                                self.test_api.dut_tracking_test_data,
                                message=TrackingPolicyCfg()))

  def _has_valid_commit(self, config, commit, manifest):
    """Determine if the builder has a valid commit.

    Public builders should sync to a commit for the public manifest and private
    builders should sync to a commit for the internal manifest.

    Args:
      config (BuilderConfig): The builder config, or None.
      commit (GitilesCommit): The gitiles commit to use, or None.
      manifest (ManifestProject): The manifest expected.

    Returns:
      Bool whether the builder has a valid commit.
    """
    # We only accept commits on refs/heads/.
    if not commit.ref.startswith('refs/heads/'):
      return False

    # Private builders should use the internal gitiles commit.
    if config:
      return commit in manifest

    # If there is no config (either no image is built, or the builder has been
    # deleted), then either manifest is fine.
    return (commit in self.m.src_state.internal_manifest or
            commit in self.m.src_state.external_manifest)

  def _determine_repo_state(self, config, commit, changes, choose_branch):
    """Set _gitiles_commit and _gerrit_changes.

    If the commit and/or changes are other than what was given, that is added as
    an output property in a nested step.

    Args:
      config (BuilderConfig): The builder config, or None.
      commit (GitilesCommit): The gitiles commit to use.  Default: value from
        buildbucket, or GitilesCommit(..., ref='refs/heads/snapshot').
      changes: (list[GerritChange]): The gerrit changes to apply.  Default: The
          currently stored list (initially the list from buildbucket.)
      choose_branch (bool): Whether to choose a branch when none is provided.
    """
    commit = commit or self.m.src_state.gitiles_commit
    changes = self.m.src_state.gerrit_changes if changes is None else changes
    original_commit = commit

    # If we have no gitiles_commit, then we were (likely) launched directly by
    # either luci-scheduler (no changes), luci-cq (changes), or a user.
    # The builder is private unless the config says otherwise.  Builders with no
    # builder config can pass a commit, or default to the internal.
    private = not (config and
                   config.general.manifest == BuilderConfig.General.PUBLIC)

    # Determine which manifest this builder should be using.
    manifest = self.m.src_state.external_manifest
    if private:
      manifest = self.m.src_state.internal_manifest

    # If the gitiles_commit we received is neither manifest, but has a ref,
    # consider honoring that.
    if (commit.ref and self._properties.honor_gitiles_commit_ref and
        not self._has_valid_commit(None, commit, manifest)):
      commit = manifest.as_gitiles_commit_proto
      # TODO(crbug/1152875): Once manifest-internal is on main on all supported
      # branches, this is not needed.  Meanwhile, if the original ref matches
      # the external manifest (which has moved), then use the manifest ref from
      # the active manifest.
      if original_commit.ref != self.m.src_state.external_manifest.ref:
        commit.ref = original_commit.ref

    # If we have a config, and the given commit is invalid, try the one from the
    # builder config.
    if config and not self._has_valid_commit(config, commit, manifest):
      commit = ConvertPB(config.orchestrator.gitiles_commit, GitilesCommit)

    # If we still do not have a valid commit, then we need to figure one out.
    # Use the appropriate snapshot from the appropriate manifest.
    if not self._has_valid_commit(config, commit, manifest):
      commit = manifest.as_gitiles_commit_proto
      if choose_branch:
        commit.ref = 'refs/heads/{}snapshot'.format(
            'staging-' if self._is_staging else '')
      else:
        # No valid commit, but we don't get to choose one.  Clear it, and do not
        # set build_manifest.
        commit.ref = ''
        commit.id = ''

    if commit and commit.ref and not commit.id:
      # If there is no commit id, fetch the current commit id for the reference.
      if not commit.id:
        test_data = dict(
            branch=dict(revision='%s-HEAD-SHA' % commit.ref.split('/')[-1]))
        commit.id = self.m.gitiles.fetch_revision(commit.host, commit.project,
                                                  commit.ref,
                                                  test_output_data=test_data)

    # If we are not ignoring the changelist in the config then insert any such
    # to the changelist.
    extra_changes = []
    if config and not self._properties.ignore_config_changelist:
      extra_changes = [
          ConvertPB(x, GerritChange) for x in config.orchestrator.gerrit_changes
      ]
    if extra_changes:
      changes = extra_changes + [x for x in changes if x not in extra_changes]

    # If there is no config, then either manifest is allowed.  If there is, then
    # the assignment above is correct.
    if commit and commit.id and not config:
      manifest = (
          self.m.src_state.internal_manifest
          if commit in self.m.src_state.internal_manifest else
          self.m.src_state.external_manifest)

    # Record the decision for later.  Saving the values in src_state will log
    # what we chose to use (rather than what we were given.)
    self.m.src_state.gitiles_commit = commit
    if manifest:
      self.m.src_state.build_manifest = manifest
    self.m.src_state.gerrit_changes = changes or []

  def _get_package_git_revision(self):
    """Return the git_revision from our cipd package."""
    ret = None
    package = self.m.buildbucket.build.exe.cipd_package
    if package:
      version = self.m.buildbucket.build.exe.cipd_version
      desc = self.m.cipd.describe(package, version)
      for tag in desc.tags:
        if tag.tag.startswith('git_revision'):
          self._package_git_revision = tag.tag.split(':')[1]
          ret = self._package_git_revision
    return ret

  def configure_builder(self, commit=None, changes=None, is_staging=None,
                        name='configure builder', choose_branch=True):
    """Configure the builder.

    Fetch the builder config.
    Determine the actual commit and changes to use.
    Set the bisect_builder and use_flags.

    Args:
      commit (GitilesCommit): The gitiles commit to use.  Default:
          GitilesCommit(.... ref='refs/heads/snapshot').
      changes (list[GerritChange]): The gerrit changes to apply.  Default: the
          gerrit_changes from buildbucket.
      is_staging (bool): Whether the builder is staging, or None to have
          configure_builder determine, based on buildbucket bucket and/or
          config.general.environment.
      name (string): Step name.  Default: "configure builder".

    Returns:
      BuilderConfig or None
    """
    build = self.m.buildbucket.build
    with self.m.step.nest(name) as presentation:
      easy_props = dict(recipes_git_revision=self.package_git_revision)
      easy_props.update(
          {'experiments': self.experiments} if self.experiments else {})
      self.m.easy.set_properties_step(**easy_props)

      config = self.config
      if config:
        # The url can be constructed from output.properties.config_ref:
        # ('+/%s/%s' % (CHROME_OS_REPO_URL, self._config_ref, filename))
        presentation.logs['builder config'] = [str(config)]
      else:
        presentation.step_text = 'config not found, assuming deleted'

      if is_staging is None:
        is_staging = (
            build.builder.bucket == 'staging' or
            build.builder.builder.startswith('staging-') or
            (config and
             config.general.environment == BuilderConfig.General.STAGING))
      self._is_staging = is_staging

      parent = [x.value for x in build.tags if x.key == 'parent_buildbucket_id']
      if parent:
        presentation.links['parent link'] = (
            self.m.buildbucket.build_url(build_id=parent[0]))

      # TODO(crbug/1053073): once changes is being stripped by callers, we can
      # drop the check of apply_gerrit_changes.
      # For now, we need to handle this here.
      if (changes and config and config.HasField('build') and
          not config.build.apply_gerrit_changes):
        changes = []

      self._determine_repo_state(config, commit, changes,
                                 choose_branch=choose_branch)

    self._is_configured = True
    return config

  def get_build_target(self, build=None):
    """Return the build target from input properties.

    Args:
      build (Build): A buildbucket build, which is expected to have a
          'build_target' input property, or None for the current build.

    Returns:
      (BuildTarget) The build target, or None.
    """
    build = build or self.m.buildbucket.build
    target = None
    if '$chromeos/build_menu' in build.input.properties:
      target = ParseDict(build.input.properties['$chromeos/build_menu'],
                         BuildMenuProperties(),
                         ignore_unknown_fields=True).build_target
      if target.name:
        return target

    # TODO(crbug/1099259): Once everyone is looking at (and setting) the
    # build_menu properties, stop looking at the global ones.
    target = ParseDict(build.input.properties, BuildTargetProperties(),
                       ignore_unknown_fields=True).build_target
    return target if target and target.name else None

  def get_build_target_name(self, build=None):
    """Return the build target name from input properties.

    Args:
      build (Build): A buildbucket build, which is expected to have a
          'build_target' input property, or None for the current build.

    Returns:
      (str) The name of the build target, or None.
    """
    build = build or self.m.buildbucket.build
    target = self.get_build_target(build=build)
    return target.name if target and target.name else None

  def build_target_dict(self, builds):
    """Take a list of builds and return a map of build_target names to build.

    This function will omit any builds that don't define input build targets.

    Args:
      builds (list[Build]): builds to extract build_target.name set from.

    Returns: a dict(str, Build) of build_target names.
    """
    build_targets = {self.get_build_target_name(b): b for b in builds}
    build_targets.pop(None, None)
    return build_targets
