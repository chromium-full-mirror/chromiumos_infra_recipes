# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for build steps"""

import collections
import contextlib
import json
import re

from typing import Iterable, Iterator, List, Optional, Tuple

from google.protobuf import json_format

from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromite.api.depgraph import DepGraph
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromite.api.test import BuildTestServiceContainersRequest
from PB.chromite.api.test import BuildTestServiceContainersResponse
from PB.chromite.api.toolchain import SetupToolchainsRequest
from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as rdb_common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2

from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

from recipe_engine import config_types
from recipe_engine import recipe_api


def _get_profile(config: BuilderConfig) -> common_pb2.Profile:
  # TODO(b/187793272): config.build.portage_profile is migrating.
  return common_pb2.Profile(name=config.build.portage_profile.profile)


class BuildMenuApi(recipe_api.RecipeApi):
  """A module with steps used by image builders.

  Image builders do not call other recipe modules directly: they always get
  there via this module, and are a simple sequence of steps.
  """

  UPLOADABLE_PREBUILTS = [
      BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
  ]

  # Allow uploading host binpkgs from amd64-generic-snapshot builder to fill
  # gaps between runs of the SDK builder.
  UPLOADABLE_HOST_PREBUILTS = ['amd64-generic']

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._container_version_fmt = props.container_version_format
    self._chroot_created = False
    self._dep_graph = None
    self._sdk_reuse_checked = False
    self._target_versions = None
    self._build_target = props.build_target
    self._force_relevant_build = props.force_relevant_build
    self._artifact_build = props.artifact_build
    self._test_with_code_coverage = props.test_with_code_coverage
    self._test_with_rust_code_coverage = props.test_with_rust_code_coverage
    self._override_prebuilts_config = props.override_prebuilts_config
    # Prebuilt information for the builder.  Created in setup_sysroot, used
    # there and install_packages.
    self._package_indexes = None
    self._force_empty_toolchain_targets = props.force_empty_toolchain_targets
    self._resultdb_gitiles_commit = None

    self._cl_affected_sysroot_packages = None
    # Installed packages can be a prereq for methods in other modules, such as
    # builder_metadata.
    self.packages_installed = False
    self._built_images = None

  def initialize(self):
    self._force_empty_toolchain_targets |= (
        'chromeos.build_menu.force_empty_toolchain_targets' in
        self.m.cros_infra_config.experiments)

    self._force_relevant_build |= (
        self.m.buildbucket.build.input.properties['force_relevant_build']
        if 'force_relevant_build' in self.m.buildbucket.build.input.properties
        else False)

  @property
  def artifact_build(self):
    return self._artifact_build

  @property
  def build_target(self):
    return self._build_target

  @property
  def config(self):
    return self.m.cros_infra_config.config

  @property
  def config_or_default(self):
    return self.m.cros_infra_config.config_or_default

  @property
  def container_version(self):
    """Return the version string for containers.

    Run through the format string, and replace any allowed fields with
    their runtime values. If any unknown fields are encountered, then a
    RuntimeError is thrown.
    """

    staging_prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''

    # Replace any explicitly allowed fields
    ALLOWED_FIELDS = {
        '{build-target}': self._build_target.name,
        '{cros-version}': self.m.cros_version.version,
        '{bbid}': self.m.buildbucket.build.id or 'led-launch',
        '{staging?}': staging_prefix,
    }

    # Get the format string, empty version is fine so just return it
    version = self._container_version_fmt
    if not version:
      return ''

    for field, value in ALLOWED_FIELDS.items():
      version = version.replace(field, str(value))

    # Make sure that no residual fields are left
    fields = re.findall(r'(\{[^{}]+\})', version)
    if fields:
      raise RuntimeError(
          'Unknown fields found in version format string: {}'.format(
              ','.join(["'{}'".format(field) for field in fields]),
          ),
      )
    # Per the reference material on docker tags:
    #   A tag name must be valid ASCII and may contain lowercase and uppercase
    #   letters, digits, underscores, periods and dashes. A tag name may not
    #   start with a period or a dash and may contain a maximum of 128
    #   characters.
    if not re.match('[A-Za-z0-9_][A-Za-z0-9_.-]*$', version):
      raise RuntimeError("Invalid tag format: '{}'".format(version))

    if len(version) > 128:
      raise RuntimeError("Tag is too long: '{}' (max 128)".format(version))

    return version

  @property
  def resultdb_gitiles_commit(self) -> rdb_common_pb2.GitilesCommit():
    """Return the GitilesCommit for Sources metadata.

    The GitilesCommit is either passed in by the parent via input property when
    the build was scheduled or can be derived for non-release builders after
    syncing the source.
    """
    if (self.m.metadata.sources_gitiles_commit_override !=
        rdb_common_pb2.GitilesCommit()):
      return self.m.metadata.sources_gitiles_commit_override

    # Don't derive a ResultDB commit for release branches. We pin and commit
    # release buildspecs to a -snapshot branch rather than using the
    # (potentially unpinned) manifest-internal commit. ToT release uses pinned
    # annealing snapshots, so upload that for consistency with other ToT builds.
    config = self.config_or_default
    if config and config.id.type == BuilderConfig.Id.RELEASE and not self.m.cros_source.is_tot:
      return rdb_common_pb2.GitilesCommit()

    with self.m.context(cwd=self.m.src_state.build_manifest.path):
      position = self.m.git_footers.position_num(
          self.m.src_state.gitiles_commit.id, 999)

    gitiles_commit = json_format.MessageToDict(self.m.src_state.gitiles_commit)
    gitiles_commit['commit_hash'] = gitiles_commit.pop('id')
    gitiles_commit['position'] = position
    return json_format.ParseDict(gitiles_commit, rdb_common_pb2.GitilesCommit(),
                                 ignore_unknown_fields=True)

  @property
  def gitiles_commit(self):
    return self.m.cros_infra_config.gitiles_commit

  @property
  def gerrit_changes(self):
    return self.m.cros_infra_config.gerrit_changes

  @property
  def is_staging(self):
    return self.m.cros_infra_config.is_staging

  @property
  def sysroot(self):
    return self.m.sysroot_util.sysroot

  @property
  def target_versions(self):
    """Get the current GetTargetVersionsResponse.

    Only set after setup_sysroot_and_determine_relevance().

    Returns:
      (GetTargetVersionsResponse): A GetTargetVersionsRequest or None.
    """
    return self._target_versions

  @property
  def chroot(self):
    return self.m.cros_sdk.chroot

  @property
  def dep_graph(self):
    return self._dep_graph

  @property
  def _build_targets_for_toolchain_setup(
      self) -> Optional[List[common_pb2.BuildTarget]]:
    """Return which build targets need toolchains, if any.

    Returns:
      For most image builds, [self.build_target], since we need toolchains to
      build an image. But if this build has no build target (ex. chromite-cq),
      then None to signify that we don't need to set up toolchains at all.
    """
    if not self.build_target.name or self._force_empty_toolchain_targets:
      return None
    return [self.build_target]

  # TODO(b/189363718): This function is catered towards the slim build use case.
  # Refactor so that it can be applied to other use cases. For example, the
  # decision to include reverse dependencies should come from the config.
  def get_cl_affected_sysroot_packages(self, packages=None,
                                       include_rev_deps=False):
    """Gets the list of sysroot packages affected by the input CLs.

    Calculates the list of packages which were changed by the CLs and their
    reverse dependencies. The list is cached to avoid recalculating the list
    during subsequent calls.

    Args:
      packages (list[PackageInfo]): The list of packages for which to get
        dependencies. If none are specified the standard list of packages is
        used.
      include_rev_deps (bool): Whether to also calculate reverse dependencies.

    Returns:
      (List[PackageInfo]): A list of packages affected by the CLs.
    """
    # If no CLs in the CQ run are applied, then no packages are affected. An
    # example is when a CQ builder that uses the public manifest contains only
    # private changes.
    if not self.m.workspace_util.patch_sets:
      return []

    packages = packages or self.config_or_default.build.install_packages.packages
    if self._cl_affected_sysroot_packages is not None:
      return list(self._cl_affected_sysroot_packages)
    self._cl_affected_sysroot_packages = self.m.cros_relevance.get_package_dependencies(
        sysroot=self.sysroot, chroot=self.chroot,
        patch_sets=self.m.workspace_util.patch_sets, packages=packages,
        include_rev_deps=include_rev_deps)
    return list(self._cl_affected_sysroot_packages)

  @contextlib.contextmanager
  def configure_builder(
      self,
      missing_ok: bool = False,
      disable_sdk: bool = False,
      commit: Optional[bb_common_pb2.GitilesCommit] = None,
      targets: Iterable[common_pb2.BuildTarget] = (),
      lookup_config_with_bucket=False,
  ) -> Optional[BuilderConfig]:
    """Initial setup steps for the builder.

    This context manager returns with all of the contexts that an image builder
    needs to have when it runs, for cleanup to happen properly.

    Args:
      missing_ok: Whether it is OK if no config is found.
      disable_sdk: This builder will not be using the SDK at all. Only for
        branches with broken or no Build API.
      commit: The GitilesCommit for the build, or None.
      targets: List of build_targets for metadata_json to use instead of our
        build_target.
      lookup_config_with_bucket: If true, include builder.bucket in key when
        looking up the BuilderConfig. If the bucket is not included in the key
        and there are builders with the same name (in different buckets), it is
        undefined which BuilderConfig is returned. The bucket will eventually
        be included in the key by default, see b/287633203.

    Returns:
      BuilderConfig for the active build (or None if the active build has no
      corresponding config), with an active context.
    """

    @contextlib.contextmanager
    def _maybe_context(ctx_func, *args, **kwargs):
      if ctx_func:
        with ctx_func(*args, **kwargs) as ret:
          yield ret
      else:
        yield

    with self.m.bot_cost.build_cost_context():
      build = self.m.buildbucket.build
      changes = build.input.gerrit_changes
      commit = commit or self.m.buildbucket.gitiles_commit
      config = self.m.cros_source.configure_builder(
          commit, changes, lookup_config_with_bucket=lookup_config_with_bucket)
      targets = targets or [self.build_target]
      if changes and config and not config.build.apply_gerrit_changes:
        raise recipe_api.StepFailure(
            'Changes provided, but builder does not apply changes')
      if config:
        self.m.cros_sdk.set_use_flags(config.build.use_flags)
      if not config and not missing_ok:
        raise recipe_api.StepFailure('Missing configuration for {}'.format(
            build.builder.builder))
      with self.m.workspace_util.setup_workspace(), \
          _maybe_context(None if disable_sdk
                         else self.m.cros_sdk.cleanup_context):
        with _maybe_context(self.m.metadata_json.context if config else None,
                            config, targets):
          yield config

        # If we have applied patches and the SDK was not validated, then we
        # need to do so before leaving the context.
        if (self._chroot_created and self.m.workspace_util.patch_sets and
            not self._sdk_reuse_checked):
          self.get_dep_graph_and_validate_sdk_reuse()

  @contextlib.contextmanager
  def setup_workspace_and_chroot(
      self, no_chroot_timeout: bool = False, cherry_pick_changes: bool = True,
      bootstrap_chroot: bool = False, replace: bool = False,
      force_no_chroot_upgrade: Optional[bool] = None) -> Iterator[bool]:
    """Setup the workspace and chroot for the builder.

    This context manager sets up the workspace path.

    Args:
      no_chroot_timeout: Whether to allow unlimited time to create the chroot.
      cherry_pick_changes: Whether to apply gerrit changes on top of the
        checkout using cherry-pick. If set to False, will directly checkout
        the changes using the gerrit fetch refs.
      bootstrap_chroot: Whether to bootstrap the chroot.
      replace: Whether to replace the chroot if it already exists.
      force_no_chroot_upgrade: Whether to prevent the chroot upgrading at all.
    Returns:
      Whether the build is relevant.
    """
    with self.setup_workspace(cherry_pick_changes=cherry_pick_changes):
      yield self.setup_chroot(no_chroot_timeout, bootstrap=bootstrap_chroot,
                              replace=replace,
                              force_no_chroot_upgrade=force_no_chroot_upgrade)

  @contextlib.contextmanager
  def setup_workspace(self, cherry_pick_changes=True):
    """Setup the workspace for the builder.

    Args:
      cherry_pick_changes (bool): Whether to apply gerrit changes on top of the
        checkout using cherry-pick. If set to False, will directly checkout
        the changes using the gerrit fetch refs.
    """
    # If we do not have a config, use an empty one.
    config = self.config_or_default

    # Set up source checkouts.
    with self.m.workspace_util.sync_to_commit(staging=self.is_staging):

      # Apply any appropriate gerrit changes.
      ignore_missing_projects = (
          config.general.manifest == BuilderConfig.General.PUBLIC)
      if cherry_pick_changes:
        self.m.workspace_util.apply_changes(
            ignore_missing_projects=ignore_missing_projects)
      else:
        for change in self.m.src_state.gerrit_changes:
          self.m.workspace_util.checkout_change(change=change)

      # The CrOS verison can be reported once the workspace is synced.
      version = self.m.cros_version.version
      self.m.easy.set_properties_step(chromeos_version=str(version))

      # Sources can be uploaded once the workspace is synced.
      self.upload_sources(config)

      yield

  def setup_chroot(self, no_chroot_timeout: bool = False,
                   sdk_version: Optional[str] = None, bootstrap: bool = False,
                   replace: bool = False, uprev_packages: bool = True,
                   setup_toolchains_if_no_update: bool = True,
                   force_no_chroot_upgrade: Optional[bool] = None) -> bool:
    """Setup the chroot for the builder.

    Args:
      no_chroot_timeout: Whether to allow unlimited time to create the chroot.
      sdk_version: Specific SDK version to include in the sdk CreateRequest:
        for example, 2022.01.20.073008.
      bootstrap: Whether to bootstrap the chroot.
      replace: Whether to replace the chroot if it already exists.
      uprev_packages: Whether to uprev packages.
      setup_toolchains_if_no_update: If True, and the function skips updating
        the chroot (whether due to the `update` kwarg or due to the builder
        config), then it will setup toolchains instead.
      force_no_chroot_upgrade: If True, chroot update is skipped.

    Returns:
      Whether the build is relevant.
    """
    # If we do not have a config, use an empty one.
    config = self.config_or_default

    relevance = Relevance.UNKNOWN
    if self.artifact_build:
      # Early check to see if the build is pointless. (No chroot nor
      # sysroot yet.)
      relevance = self.m.sysroot_util.update_for_artifact_build(
          None, config.artifacts, force_relevance=self._force_relevant_build)

    if not self.artifact_build or relevance != Relevance.POINTLESS:
      if uprev_packages:
        self.m.cros_source.uprev_packages()
      # Kick off a chrome source checkout on main asynchronously. Check the
      # docs of the chrome module for more information.
      if ('chromeos.build_menu.chrome_sync'
          in self.m.cros_infra_config.experiments):
        self.m.chrome.sync_chrome_async(config, self.build_target)

      self.m.cros_sdk.create_chroot(
          version=config.general.sdk_cache_version, bootstrap=bootstrap,
          sdk_version=sdk_version,
          timeout_sec=None if config.build.sdk_update.compile_source or
          no_chroot_timeout else 'DEFAULT', replace=replace)
      self._chroot_created = True

      if force_no_chroot_upgrade is not True:
        self.m.cros_sdk.update_chroot(
            build_source=config.build.sdk_update.compile_source,
            toolchain_targets=self._build_targets_for_toolchain_setup)
      elif setup_toolchains_if_no_update:
        # Normally, update_chroot takes care of toolchain setup. If we skipped
        # update_chroot, make sure we still setup toolchains.
        self.setup_toolchains()

    return relevance != Relevance.POINTLESS

  def setup_toolchains(self) -> None:
    """Setup toolchains on the builder.

    ToolchainService.SetupToolchains was added in R117. If this function runs
    on an older branch, then Chromite will not have the endpoint implementation,
    so the build will fail. At time of writing, this function is not expected
    to run on any branches older than that. If that changes, consider cherry-
    picking SetupToolchains into your branch: https://crrev.com/c/4659850.

    This is a noop if we have no build targets to setup.

    Raises:
      InfraFailure: If the endpoint is not available.
    """
    build_targets = self._build_targets_for_toolchain_setup
    if not build_targets:
      return
    with self.m.step.nest('setup toolchains'):
      if not self.m.cros_build_api.has_endpoint(
          self.m.cros_build_api.ToolchainService, 'SetupToolchains'):
        raise recipe_api.InfraFailure(
            'Endpoint SetupToolchains() not present on branches older than '
            'R117. Consider cherry-picking it in.')
      request = SetupToolchainsRequest(chroot=self.chroot, boards=build_targets)
      self.m.cros_build_api.ToolchainService.SetupToolchains(request)

  def setup_sysroot_and_determine_relevance(self, with_sysroot=True,
                                            snapshot_commit=None):
    """Setup the sysroot for the builder and determine build relevance.

    Args:
      with_sysroot (bool): Whether to create a sysroot.  Default: True.
        (Some builders do not require a sysroot.)
      snapshot_commit (GitilesCommit): The snapshot commit to use for getting
        prebuilts metadata, or None to use the commit the builder is
        configured with.

    Returns:
      An object containing:
        pointless (bool): Whether the build is pointless.
        packages (list[PackageInfo]): The packages for this build, or an empty
          list.
    """
    _env_info = collections.namedtuple('env_info', ['pointless', 'packages'])

    # If we do not have a config, use an empty one.
    config = self.config_or_default
    artifacts = config.artifacts

    if with_sysroot:
      # TODO(crbug/1112425): config.build.portage_profile is migrating.
      profile = common_pb2.Profile(name=config.build.portage_profile.profile)
      self._package_indexes = self.m.cros_prebuilts.get_package_index_info(
          config.artifacts.prebuilts_gs_bucket, snapshot=snapshot_commit or
          self.gitiles_commit, build_target=self.build_target, profile=profile)
      self.m.sysroot_util.create_sysroot(
          self.build_target, profile, package_indexes=self._package_indexes,
          use_cq_prebuilts=artifacts.use_cq_prebuilts)

      # Set the target_versions output property, and upload metatdata.
      # This requires a sysroot for at least the package versions.
      self._target_versions = self.m.cros_build_api.PackageService.GetTargetVersions(
          GetTargetVersionsRequest(
              chroot=self.m.cros_sdk.chroot, build_target=self.build_target,
              packages=config.build.install_packages.packages))

      target_versions = json_format.MessageToDict(
          self.target_versions, including_default_value_fields=True)
      self.m.easy.set_properties_step(target_versions=target_versions)
      if self.m.cros_artifacts.has_output_artifacts(artifacts.artifacts_info):
        self.m.metadata_json.add_version_entries(target_versions)
        self.m.metadata_json.upload_to_gs(config, [self.build_target],
                                          partial=True)

    dep_graph = self.get_dep_graph_and_validate_sdk_reuse()

    relevant = True
    # Only CQ and Postsubmit builders undergo a relevancy check.
    if config.id.type == BuilderConfig.Id.POSTSUBMIT:
      relevant = self.m.cros_relevance.postsubmit_relevance_check(
          self.gitiles_commit, dep_graph.target)
      # Adding relevance to tags to help cros_fleet and others search for
      # latest postsubmit image. See b/205142684.
      self.m.cros_tags.add_tags_to_current_build(
          **{'relevance': '{}relevant'.format('' if relevant else 'not ')})
    elif config.id.type == BuilderConfig.Id.CQ:
      # In the cases where force_relevant is True:
      # 1. input_properties.force_relevant_build is True, and/or
      # 2. output_properties.testing_toolchain is True (now tracked in
      #    cros_relevance), and/or
      # 3. output_properties.artifact_prep is True.
      #    TODO(b/205159611): We don't currently check for artifact_prep when
      #    determining relevance. Investigate whether this check is now obsolete
      #    or should be added.
      # 4. The gerrit change contains the appropriate footer. The footers are read
      #    in the orchestrator and passed in as an input property (1) therefore we
      #    do not need to read the footers here.
      relevant = self.m.cros_relevance.is_cq_build_relevant(
          self.m.workspace_util.patch_sets, dep_graph.target,
          force_relevant=self._force_relevant_build)

    if not relevant:
      self.m.buildbucket.hide_current_build_in_gerrit()

    packages = self.config_or_default.build.install_packages.packages
    return _env_info(not relevant, packages)

  def get_dep_graph_and_validate_sdk_reuse(self):
    """Fetch the dependency graph, and validate the SDK for reuse.

    Note that failure to validate the SDK for reuse is not considered fatal, but
    the SDK will be marked as dirty out of an abundance of caution.

    Returns:
      The dependency graph from cros_relevance.get_dependency_graph.
    """
    dep_graph = self._get_dep_graph()
    # Being unable to validate the SDK graph because of quota exhaustion when
    # calling the pointless build checker should not be fatal. Catch the
    # failures here and try again at the end of the build.
    try:
      self._validate_sdk_reuse()
    # If we fail to validate the SDK, just mark it dirty out of an abundance
    # of caution. The SDK gets invalidated on all build failures anyway, so this
    # would at least allow the current run to pass.
    except recipe_api.StepFailure:
      self.m.cros_sdk.mark_sdk_as_dirty()

    return dep_graph

  def _get_dep_graph(self) -> DepGraph:
    """Fetch the dependency graph."""
    config = self.config_or_default
    packages = config.build.install_packages.packages

    self._dep_graph = (
        self._dep_graph or self.m.cros_relevance.get_dependency_graph(
            sysroot=self.sysroot, chroot=self.chroot, packages=packages))
    return self.dep_graph

  def _validate_sdk_reuse(self):
    with self.m.step.nest('validate SDK reuse'):
      # If any of the changes affect the sdk, mark the sdk as dirty.
      if self.m.cros_relevance.is_depgraph_affected(
          self.gerrit_changes, self.gitiles_commit,
          dep_graph=self._dep_graph.sdk,
          test_value=self.m.workspace_util.toolchain_cls_applied):
        self.m.cros_sdk.mark_sdk_as_dirty()
    self._sdk_reuse_checked = True

  def bootstrap_sysroot(self, config=None):
    """Bootstrap the sysroot by installing the toolchain.

    Args:
      config (BuilderConfig): The Builder Config for the build. If none, will
        attempt to get the BuilderConfig whose id.name matches the specified
        Buildbucket builder from HEAD.
    """
    # Make sure we have a valid config
    config = config or self.config_or_default
    self.m.sysroot_util.bootstrap_sysroot(
        compile_source=config.build.install_toolchain.compile_source)

  def install_packages(self, config=None, packages=None, timeout_sec='DEFAULT',
                       name=None, force_all_deps=False, include_rev_deps=False,
                       dryrun=False, package_indexes=None):
    """Install packages as appropriate.

    The config determines whether to call install packages. If installing
    packages, fetch Chrome source when needed.

    Args:
      config (BuilderConfig): The Builder Config for the build.
      packages (list[PackageInfo]): List of packages to install.  Default: all
        packages for the build_target.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      name (string): Step name for install packages, or None for default.
      force_all_deps (bool): Whether to force building of all dependencies.
      include_rev_deps (bool): Whether to also install reverse dependencies.
        Ignored if config specifies ALL_DEPENDENCIES or force_all_deps is True.
      dryrun (bool): Dryrun the install packages step.
      package_indexes (list[PackageIndexInfo]): List of prebuilts metadata to be
        used when installing packages.

    Returns:
      (bool): Whether to continue with the build.
    """
    # Make sure we have a valid config
    config = config or self.config_or_default
    install_packages = config.build.install_packages
    relevant_packages = packages
    if not force_all_deps and (config.build.install_packages.dependencies ==
                               BuilderConfig.CL_AFFECTED_DEPENDENCIES):
      relevant_packages = self.get_cl_affected_sysroot_packages(
          packages=relevant_packages, include_rev_deps=include_rev_deps)
      # Ensure implicit dependencies are installed.
      relevant_packages.append(
          common_pb2.PackageInfo(category='virtual',
                                 package_name='implicit-system'))
    if self.m.cros_infra_config.should_run(install_packages.run_spec):
      with self.m.context(env={'DEPOT_TOOLS_COLLECT_METRICS': '0'}):
        self.m.sysroot_util.install_packages(
            config, self.dep_graph, relevant_packages,
            artifact_build=self.artifact_build,
            package_indexes=package_indexes or self._package_indexes,
            timeout_sec=timeout_sec, name=name, dryrun=dryrun)
    self.packages_installed = not self.m.cros_infra_config.should_exit(
        install_packages.run_spec)
    return self.packages_installed

  def build_images(self, config=None, include_version=False):
    """Build the image.

    This behavior is adjusted by the run_spec values in config.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      include_version (bool): Whether or not to pass the workspace version
        to sysroot_util.build.
    """
    config = config or self.config_or_default
    build_images = config.build.build_images
    unit_tests = config.unit_tests

    builder_path = self.m.cros_artifacts.artifacts_gs_path(
        config.id.name, self.build_target, config.id.type,
        template=self.m.cros_artifacts.gs_upload_path)
    version = (
        self.m.cros_version.version.platform_version
        if include_version else None)
    bazel = build_images.build_images_orchestrator == BuilderConfig.BAZEL

    self._built_images = self.m.sysroot_util.build_images(
        build_images.image_types, builder_path,
        build_images.disable_rootfs_verification, build_images.disk_layout,
        build_images.base_is_recovery, version=version,
        skip_image_tests=unit_tests.skip_image_tests,
        verify_image_size_delta=build_images.verify_image_size_delta,
        bazel=bazel)

  def unit_test_images(self, config=None):
    """Run ebuild tests.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    Returns:
      (bool): Whether to continue with the build.
    """
    config = config or self.config_or_default
    unit_tests = config.unit_tests

    self.run_unittests(config)

    return not self.m.cros_infra_config.should_exit(unit_tests.ebuilds_run_spec)

  def build_and_test_images(self, config=None, include_version=False):
    """Build the image and run ebuild tests.

    This behavior is adjusted by the run_spec values in config.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      include_version (bool): Whether or not to pass the workspace version
        to sysroot_util.build.
    Returns:
      (bool): Whether to continue with the build.
    """
    self.build_images(config, include_version)
    return self.unit_test_images(config)

  def run_unittests(self, config=None):
    """run ebuild tests as specified by config.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """

    def _has_manifest_changes(presentation):
      affected_paths = self.m.cros_relevance.get_affected_paths(
          self.m.workspace_util.patch_sets)
      manifest_changes_present = any(
          re.match(r'^(manifest-internal|manifest)\/.*\.xml$', p)
          for p in affected_paths)
      if manifest_changes_present:
        presentation.step_text = 'running all unit tests on manifest changes'
      return manifest_changes_present

    unit_tests = config.unit_tests

    if self.m.cros_infra_config.should_run(unit_tests.ebuilds_run_spec):
      with self.m.step.nest('run ebuild tests') as presentation:
        relevant_testable_packages = unit_tests.packages
        testable_packages_optional = False
        filter_only_cros_workon = False
        bazel = unit_tests.unit_tests_orchestrator == BuilderConfig.BAZEL
        if (config.unit_tests.dependencies
            == BuilderConfig.CL_AFFECTED_DEPENDENCIES and
            not _has_manifest_changes(presentation)):
          testable_packages_optional = True
          filter_only_cros_workon = True
          relevant_testable_packages = self.get_cl_affected_sysroot_packages(
              include_rev_deps=True)
          # If the config specifies packages to test, only test the specified
          # packages which were affected by the CL.
          # The PackageInfo objects returned by the depgraph contain versions
          # while the ones in the config do not, therefore only compare category
          # and package_name fields.
          if unit_tests.packages:
            relevant_testable_packages = [
                x for x in self._cl_affected_sysroot_packages or []
                if common_pb2.PackageInfo(category=x.category,
                                          package_name=x.package_name) in list(
                                              unit_tests.packages)
            ]

          # Exit early if there are no relevant packages.
          if not relevant_testable_packages:
            presentation.step_text = 'no relevant packages to test'
            return

        request = BuildTargetUnitTestRequest(
            build_target=self.build_target,
            chroot=self.m.cros_sdk.chroot,
            package_blocklist=unit_tests.package_blocklist,
            packages=relevant_testable_packages,
            flags=BuildTargetUnitTestRequest.Flags(
                code_coverage=self._test_with_code_coverage,
                rust_code_coverage=self._test_with_rust_code_coverage,
                empty_sysroot=unit_tests.empty_sysroot,
                testable_packages_optional=testable_packages_optional,
                filter_only_cros_workon=filter_only_cros_workon, bazel=bazel),
            results_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=str(self.m.path.mkdtemp()),
                    location=common_pb2.Path.OUTSIDE)),
        )
        response = self.m.cros_build_api.TestService.BuildTargetUnitTest(
            request,
            # Asan builders take longer than 2.5 hrs. https://crbug.com/1170372.
            timeout=3 * 60 * 60,
            response_lambda=self.m.cros_build_api.failed_pkg_data_names,
            pkg_logs_lambda=self.m.cros_build_api.failed_pkg_logs)
        pkgs = self.m.cros_build_api.failed_pkg_logs(request, response)
        self.m.failures.set_test_failed_packages(presentation, pkgs)

  def upload_artifacts(
      self, config=None, private_bundle_func=None, sysroot=None,
      report_to_spike=False, name='upload artifacts',
      previously_uploaded_artifacts=None,
      ignore_breakpad_symbol_generation_errors=False
  ) -> Tuple[Optional[UploadedArtifacts], Optional[config_types.Path]]:
    """Upload artifacts from the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      private_bundle_func (func): If a private bundling method is needed (such
        as when there is no Build API on the branch), this will be called
        instead of the internal bundling method.
      sysroot (Sysroot): Use this sysroot.  Defaults to the primary Sysroot for
        the build.
      report_to_spike (bool): If True, will call bcid_reporter to report artifact
        information and trigger Spike to upload the provenance.
      name (str): The step name. Defaults to 'upload artifacts'.
      previously_uploaded_artifacts(UploadedArtifacts): The UploadedArtifacts
        from a previous call to upload_artifacts; if set, these artifact
        types will not be re-uploaded. This used to avoid re-bundling artifacts
        if upload_artifacts is called multiple times.
      ignore_breakpad_symbol_generation_errors: If True, the
        BREAKPAD_DEBUG_SYMBOLS step will ignore any errors during symbol
        generation.

    Returns:
      (Option[UploadedArtifacts]) information about uploaded artifacts, if any
            exist.
    """
    config = config or self.config_or_default
    sysroot = sysroot or self.sysroot or Sysroot(build_target=self.build_target)
    # Check if the unit tests are being run. Only run upload coverage step if true.
    # If tests are not run, we dont have the coverage data and this step should be skipped.
    unit_test_configured = self.m.cros_infra_config.should_run(
        config.unit_tests.ebuilds_run_spec)
    run_upload_coverage = self.packages_installed and unit_test_configured

    if self.m.cros_artifacts.has_output_artifacts(
        config.artifacts.artifacts_info):
      return self.m.cros_artifacts.upload_artifacts(
          config.id.name, config.id.type, config.artifacts.artifacts_gs_bucket,
          artifacts_info=config.artifacts.artifacts_info, chroot=self.chroot,
          sysroot=sysroot, private_bundle_func=private_bundle_func,
          report_to_spike=report_to_spike,
          attestation_eligible=config.artifacts.attestation_eligible,
          upload_coverage=run_upload_coverage, name=name,
          previously_uploaded_artifacts=previously_uploaded_artifacts,
          ignore_breakpad_symbol_generation_errors=ignore_breakpad_symbol_generation_errors
      )
    return (None, None)

  def artifacts_build_path(self):
    """Get the standard artifacts build path for the builder (without bucket).

    For example betty-arc-r-release/R114-15436.0.0

    This method will only work if the checkout has already been initialized,
    as we rely on the CrOS version (and thus the version file).
    """
    config = self.config_or_default
    gs_path = self.m.cros_artifacts.artifacts_gs_path(
        config.id.name, self._build_target, config.id.type,
        template=self.m.cros_artifacts.gs_upload_path)
    return gs_path

  def artifacts_gs_path(self):
    """Get the standard artifacts GS path for the builder (including bucket).

    This method will only work if the checkout has already been initialized,
    as we rely on the CrOS version (and thus the version file).
    """
    config = self.config_or_default
    gs_bucket = config.artifacts.artifacts_gs_bucket
    gs_path = self.artifacts_build_path()
    return 'gs://{gs_bucket}/{gs_path}'.format(gs_bucket=gs_bucket,
                                               gs_path=gs_path)

  def _read_container_info_gcs_file(
      self, gs_path) -> Optional[BuildTestServiceContainersResponse]:
    """Read the file content, returns cached test service container based on file status

    Reads the json node "status" inside the file and if found "complete", parses the JSON to
    BuildTestServiceContainersResponse. If not found or status is not "completed", returns None.

    Args:
      gs_path (str): The GCS path to the file to be read.

    Returns:
      BuildTestServiceContainersResponse or None
    """
    with self.m.step.nest('reading cached container info from gs path: ' +
                          gs_path) as presentation:
      response = self.m.gsutil.cat(
          gs_path, stdout=self.m.raw_io.output_text(name='cat results',
                                                    add_output_log=True),
          ok_ret=(0, 1), use_retry_wrapper=True)
      presentation.logs['cached container gcs'] = response.stdout
      if response.stdout:
        response_json = json.loads(response.stdout.strip())
        status = response_json['status']
        if status == 'completed':
          builder_response = BuildTestServiceContainersResponse()
          builder_response = json_format.Parse(response.stdout,
                                               builder_response,
                                               ignore_unknown_fields=True)
          return builder_response
        presentation.step_summary_text = "status: '{}'".format(status)
      return None

  def _get_cached_container_metadata_gcs(
      self, gs_path, timeout,
      interval) -> (Optional[BuildTestServiceContainersResponse]):
    """Reads all file at given gs path and returns cached test service container

    This function reads the contents of all files from a specified GCS path. It lists all files
    and calls read_container_info_gcs_file on each at requested time interval. Immediately returns
    if valid service response is returned. If not found within the specified maximum execution time,
    it returns None at the end of that time period.

    Args:
      gs_path (str): The GCS path to the file to be read.
      timeout (int): The maximum execution time in seconds.
      interval (int): Time interval before reading

    Returns:
      build_test_container_response (BuildTestServiceContainersResponse): BuildTestServiceContainersResponse or None
    """
    with self.m.step.nest('cached container info from gcs') as presentation:
      start_time = self.m.time.time()
      attempt_counter = 1
      # Run the loop for {timeout} seconds at {interval} seconds
      while self.m.time.time() - start_time < timeout:
        with self.m.step.nest(
            'attempt-{}'.format(attempt_counter)) as interval_presentation:
          response = self.m.gsutil.list(
              gs_path, timeout=1 * 30,
              stdout=self.m.raw_io.output_text(name='ls results',
                                               add_output_log=True),
              ok_ret=(0, 1))
          if response.stdout:
            for uri in response.stdout.split():
              container_info = self._read_container_info_gcs_file(uri)
              if container_info:
                interval_presentation.step_summary_text = 'cached container found in attempt-{}'.format(
                    attempt_counter)
                presentation.step_summary_text = "cached test container found at :'{}'".format(
                    uri)
                presentation.logs['related gcs files'] = response.stdout
                return container_info
          else:
            interval_presentation.step_summary_text = 'no files present, builder should build fresh container and upload to gcs'
            presentation.step_summary_text = 'no files present, builder should build fresh container and upload to gcs'
            return None
          self.m.time.sleep(interval)
          interval_presentation.step_summary_text = 'no cached container found in attempt-{}'.format(
              attempt_counter)
          attempt_counter = attempt_counter + 1

      presentation.step_summary_text = 'no cached container found at timeout, builder should build fresh container and upload to gcs'
      return None

  def _update_container_info_gcs(self, status, parent_build_id,
                                 build_test_container_response=None):
    """Updates gcs with test service container info and build status

    If builder is creating fresh docker containers, then it should update gcs
    once with "started" status before actual building and once build is completed
    it should update gcs with metadata and status as "completed".

    Args:
      status (str): The status of building container step. "started" or "completed"
      parent_build_id (str): Unique gspath prefix where file will be updated
      build_test_container_response (BuildTestServiceContainersResponse): BuildTestServiceContainersResponse or None

    Returns:
      None
    """
    with self.m.step.nest('update test service container build progress as: ' +
                          status) as presentation:
      if build_test_container_response:
        container_build_update = json_format.MessageToDict(
            build_test_container_response)
        container_build_update['status'] = status
      else:
        container_build_update = {'status': status}

      build_id = self.m.buildbucket.build.id or 'led'
      with self.m.step.nest('writing update to local file'):
        tmp_dir = self.m.path.mkdtemp(prefix='cft-builder-json')
        file_path = tmp_dir.join(str(build_id) + '.json')
        self.m.file.write_json('Writing response', file_path,
                               container_build_update)

      gs_path = self.m.path.join('cft-container-json', parent_build_id,
                                 str(build_id) + '.json')
      self.m.gsutil.upload(file_path, 'chromeos-image-archive', gs_path)
      presentation.logs[
          'gs upload path'] = 'gs://chromeos-image-archive/' + gs_path

  def create_containers(self, builder_config=None):
    """Call the BuildTestServiceContainers endpoint to build test containers.

    The build API itself handles uploading generated container images to the
    container registry, but we handle collecting the metadata and uploading
    it with the build artifacts.

    Args:
      builder_config (BuilderConfig): The BuilderConfig for this build, or None

    Returns:
      None
    """
    builder_config = builder_config or self.config_or_default
    if self.container_version:
      with self.m.step.nest('create test service containers') as presentation:
        if not self.m.cros_build_api.has_endpoint(
            self.m.cros_build_api.TestService, 'BuildTestServiceContainers'):
          presentation.step_summary_text = 'No endpoint, skipping'
        else:
          build_id = self.m.buildbucket.build.id
          parent_build_id = self.m.cros_tags.get_single_value(
              'parent_buildbucket_id') or 'led-launch-' + self.m.uuid.random()
          cached_container_gs_path = 'gs://chromeos-image-archive/cft-container-json/' + parent_build_id
          # if test train then reduce it to 5 seconds to explore all code path for 100% code coverage
          timeout = 1 * 20 * 60 if self.m.cros_tags.get_single_value(
              'parent_buildbucket_id') else 5
          interval = 1 * 30 if self.m.cros_tags.get_single_value(
              'parent_buildbucket_id') else 1

          cft_cache_build_enabled = 'chromeos.build_cq.cft_cache_build' in self.m.cros_infra_config.experiments

          response = None
          # check if container info exists for parent builder in gcs. Skips building if found or creates fresh containers.
          if cft_cache_build_enabled:
            response = self._get_cached_container_metadata_gcs(
                gs_path=cached_container_gs_path, timeout=timeout,
                interval=interval)
          if response is None:
            # add status file in gcs for other builders from same parent so that they don't make fresh containers.
            if cft_cache_build_enabled:
              self._update_container_info_gcs(
                  status='started', parent_build_id=parent_build_id,
                  build_test_container_response=None)
            BuildTestServiceContainers = \
              self.m.cros_build_api.TestService.BuildTestServiceContainers
            version = self.container_version
            presentation.step_summary_text = "version: '{}'".format(version)

            response = BuildTestServiceContainers(
                BuildTestServiceContainersRequest(
                    build_target=self.build_target,
                    chroot=self.m.cros_sdk.chroot,
                    version=version,
                    tags=[version] + ([str(build_id)] if build_id else []),
                    labels={
                        'build-url':
                            'https://ci.chromium.org/b/{}'.format(build_id)
                            if build_id else 'led'
                    },
                ), timeout=1 * 60 * 60)

            # update status file in gcs for other builders from same parent to read container info.
            if cft_cache_build_enabled:
              self._update_container_info_gcs(
                  status='completed', parent_build_id=parent_build_id,
                  build_test_container_response=response)

          # Set up links to built containers.
          container_metadata = ContainerMetadata()
          container_images = container_metadata.containers[
              self.build_target.name].images

          for result in response.results:
            if result.HasField('success'):
              image_info = result.success.image_info

              # Make sure digest has the hash algorithm on it so links work
              if not image_info.digest.startswith('sha256:'):
                image_info.digest = 'sha256:' + image_info.digest

              image_link = 'https://{host}/{proj}/{name}@{hash}'.format(
                  host=image_info.repository.hostname,
                  proj=image_info.repository.project,
                  name=image_info.name,
                  hash=image_info.digest,
              )

              # Remove the sha prefix and get a subset of the digest to display.
              short_hash = image_info.digest.replace('sha256:', '')[:8]
              link_name = '{} [{}]'.format(result.name, short_hash)
              presentation.links[link_name] = image_link

              # Index the container info by container name and store in
              # the overall metadata structure that we'll upload.
              container_images[image_info.name].CopyFrom(image_info)

          # Set error status if any builds failed.
          failed = False
          for result in response.results:
            if result.HasField('failure'):
              presentation.logs['{} error log'.format(result.name)] = \
                result.failure.error_message
              failed = True

          gs_bucket = builder_config.artifacts.artifacts_gs_bucket
          gs_path = self.m.cros_artifacts.upload_metadata(
              self.m.metadata.CONTAINER_METADATA_INFO.name,
              builder_config.id.name,
              self.build_target,
              gs_bucket,
              self.m.metadata.CONTAINER_METADATA_INFO.filename,
              container_metadata,
              template=self.m.cros_artifacts.gs_upload_path,
          )

          presentation.links['container metadata (gs)'] = (
              self.m.urls.get_gs_bucket_url(gs_bucket, gs_path))

          presentation.logs[
              'container metadata (log)'] = json_format.MessageToJson(
                  container_metadata)

          if failed:
            presentation.properties['container_building_failed'] = True
            raise recipe_api.StepFailure(
                'One or more test service containers failed to build.')

          # Upload test metadata to the same gs bucket.
          test_metadata = self.m.metadata.fetch_test_metadata(
              chroot=self.chroot, sysroot=self.sysroot)
          if test_metadata:
            gs_path = self.m.cros_artifacts.upload_metadata(
                'test_metadata',
                builder_config.id.name,
                self.build_target,
                builder_config.artifacts.artifacts_gs_bucket,
                'test_metadata.jsonpb',
                test_metadata,
                template=self.m.cros_artifacts.gs_upload_path,
            )
            presentation.links['test metadata (gs)'] = (
                self.m.urls.get_gs_bucket_url(gs_bucket, gs_path))

  def upload_sources(self,
                     config: BuilderConfig) -> Optional[invocation_pb2.Sources]:
    """Add the Sources file to the build metadata artifact dir.

    Note: This should only be called after syncing to the manifest.

    Args:
      config: The builder config of this builder.

    Returns:
      sources: The Sources uploaded.
    """
    with self.m.failures.ignore_exceptions():
      # Skip if the builder is not configured to upload artifacts.
      if not config.artifacts.artifacts_gs_bucket:
        return None

      # This is currently limited to CQ, Postsubmit, and Release builders.
      if not (config and config.id.type in [
          BuilderConfig.Id.CQ, BuilderConfig.Id.POSTSUBMIT,
          BuilderConfig.Id.RELEASE
      ]):
        return None

      gitiles_commit = self.resultdb_gitiles_commit

      if gitiles_commit == rdb_common_pb2.GitilesCommit():
        return None

      changelists = [
          json_format.Parse(
              json_format.MessageToJson(x), rdb_common_pb2.GerritChange(),
              ignore_unknown_fields=True)
          for x in self.m.src_state.gerrit_changes
      ]
      # At most 10 changelists may be specified. If more than 10 changelists are
      # applied, then only include the first 10 and set is_dirty
      # http://shortn/_M8WrZaNB1H.
      if len(changelists) > 10:
        is_dirty = True
        changelists = changelists[:10]
      else:
        is_dirty = False

      sources = self.m.metadata.SOURCES_METADATA_INFO.msgtype(
          gitiles_commit=gitiles_commit, changelists=changelists,
          is_dirty=is_dirty)

      self.m.cros_artifacts.upload_metadata(
          name=self.m.metadata.SOURCES_METADATA_INFO.name,
          builder_name=config.id.name,
          target=self.build_target,
          gs_bucket=config.artifacts.artifacts_gs_bucket,
          filename=self.m.metadata.SOURCES_METADATA_INFO.filename,
          message=sources,
          template=self.m.cros_artifacts.gs_upload_path,
      )

      return sources

  def upload_prebuilts(self, config=None):
    """Upload prebuilts from the build.

    Upload prebuilts if the configuration has uploadable prebuilts.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    config = config or self.config
    artifacts = config.artifacts

    profile = _get_profile(config)
    prebuilt_target = self._override_prebuilts_config or artifacts.prebuilts
    if prebuilt_target in self.UPLOADABLE_PREBUILTS:
      self.m.cros_prebuilts.upload_target_prebuilts(
          self.build_target, self.sysroot, self.chroot, profile, config.id.type,
          artifacts.prebuilts_gs_bucket,
          private=(artifacts.prebuilts == BuilderConfig.Artifacts.PRIVATE))

  def upload_devinstall_prebuilts(self, config=None):
    """Upload dev_install prebuilts from the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    config = config or self.config
    artifacts = config.artifacts

    self.m.cros_prebuilts.upload_devinstall_prebuilts(
        self.build_target, self.sysroot, self.chroot,
        artifacts.devinstall_prebuilts_gs_bucket)

  def upload_chrome_prebuilts(self,
                              config: Optional[BuilderConfig] = None) -> None:
    """Upload Chrome prebuilts from the build.

    Args:
      config: The Builder Config for the build, or None.
    """
    config = config or self.config
    artifacts = self.config.artifacts

    profile = _get_profile(config)
    prebuilt_target = self._override_prebuilts_config or artifacts.prebuilts
    if prebuilt_target in self.UPLOADABLE_PREBUILTS:
      self.m.cros_prebuilts.upload_chrome_prebuilts(
          self.build_target, self.sysroot, self.chroot, profile,
          self.config.id.type, artifacts.prebuilts_gs_bucket,
          private=(artifacts.prebuilts == BuilderConfig.Artifacts.PRIVATE))

  def upload_host_prebuilts(self,
                            config: Optional[BuilderConfig] = None) -> None:
    """Upload host prebuilts from the build.

    Upload prebuilts if the configuration has uploadable prebuilts.

    Args:
      config: The Builder Config for the build, or None.
    """
    config = config or self.config
    artifacts = config.artifacts

    profile = _get_profile(config)
    prebuilt_target = self._override_prebuilts_config or artifacts.prebuilts
    if (prebuilt_target in self.UPLOADABLE_PREBUILTS and
        self.build_target.name in self.UPLOADABLE_HOST_PREBUILTS):
      self.m.cros_prebuilts.upload_host_prebuilts(self.build_target,
                                                  self.chroot, config.id.type,
                                                  artifacts.prebuilts_gs_bucket,
                                                  profile)

  def publish_latest_files(self, gs_bucket, gs_path):
    """Write LATEST-... files to GS.

    Writes version information to the LATEST-{version} and LATEST-{branch} files
    in the specified GS dir. Will only write LATEST-{branch} if the version is
    more recent than the existing contents.

    Args:
      gs_bucket (str): GS bucket to write to.
      gs_path (str): GS path/template to write to (relative to the bucket),
        e.g. eve-release or {target}-release.
    """
    config = self.config_or_default
    gs_path = self.m.cros_artifacts.artifacts_gs_path(config.id.name,
                                                      self.build_target,
                                                      config.id.type,
                                                      template=gs_path)

    self.m.cros_artifacts.publish_latest_files(gs_bucket, gs_path)

  def publish_image_size_data(self, config):
    """Retrieve, assemble, and publish information about package and image size.

    Only expected to produce results after a successful completion of
    ImageService/Create and PackageService/GetTargetVersions.

    Args:
      config: A BuilderConfig object.
    """
    # Ignore exceptions, since this should never be a blocker for builds.
    # TODO(b/259704135): set up monitoring.
    with self.m.failures.ignore_exceptions():
      self.m.observability_image_size.publish(config, self.build_target,
                                              self.target_versions,
                                              self._built_images, self.chroot)
