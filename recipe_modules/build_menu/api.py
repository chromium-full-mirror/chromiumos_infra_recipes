# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for build steps"""

import collections
import contextlib

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromite.api.test import BuildTestServiceContainersRequest
from PB.chromiumos.common import PackageInfo
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import Profile


class BuildMenuApi(recipe_api.RecipeApi):
  """A module with steps used by image builders.

  Image builders do not call other recipe modules directly: they always get
  there via this module, and are a simple sequence of steps.
  """

  UPLOADABLE_PREBUILTS = [
      BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
  ]

  # TODO(crbug/1099259): Migrate the common build_target properties to the
  # module, and stop looking at the global properties.
  def __init__(self, props, glob_props, *args, **kwargs):
    super(BuildMenuApi, self).__init__(*args, **kwargs)
    self._chroot_created = False
    self._dep_graph = None
    self._target_versions = None
    # Our properties: BuildMenuProperties ($chromeos/build_menu).
    # TODO(crbug/1099259): Inherit missing properties from the recipe.
    if not props.build_target.name:
      props.build_target.CopyFrom(glob_props.build_target)
    props.force_relevant_build = (
        props.force_relevant_build or glob_props.force_relevant_build)
    props.artifact_build = (props.artifact_build or glob_props.artifact_build)

    self._build_target = props.build_target
    self._force_relevant_build = props.force_relevant_build
    self._artifact_build = props.artifact_build
    self._test_with_code_coverage = props.test_with_code_coverage
    # Prebuilt information for the builder.  Created in setup_sysroot, used
    # there and install_packages.
    self._package_indexes = None
    self._force_empty_toolchain_targets = props.force_empty_toolchain_targets

    self._cl_affected_sysroot_packages = None

  def initialize(self):
    self._force_empty_toolchain_targets |= (
        'chromeos.build_menu.force_empty_toolchain_targets' in
        self.m.cros_infra_config.experiments)

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
  def gitiles_commit(self):
    return self.m.cros_infra_config.gitiles_commit

  @property
  def gerrit_changes(self):
    return self.m.cros_infra_config.gerrit_changes

  @property
  def force_relevant_build(self):
    return self._force_relevant_build

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
    packages = packages or self.config_or_default.build.install_packages.packages
    if self._cl_affected_sysroot_packages:
      return list(self._cl_affected_sysroot_packages)
    self._cl_affected_sysroot_packages = self.m.cros_relevance.get_package_dependencies(
        sysroot=self.sysroot, chroot=self.chroot,
        patch_sets=self.m.workspace_util.patch_sets, packages=packages,
        include_rev_deps=include_rev_deps)
    return list(self._cl_affected_sysroot_packages)

  @contextlib.contextmanager
  def configure_builder(self, is_staging=None, missing_ok=False,
                        disable_sdk=False, commit=None, targets=()):
    """Initial setup steps for the builder.

    This context manager returns with all of the contexts that an image builder
    needs to have when it runs, for cleanup to happen properly.

    Args:
      is_staging (bool): Whether this is a staging builder.  Use this to
          override auto-detection. By default, anything in the 'staging' bucket
          is considered a staging builder.
      missing_ok (bool): Whether it is OK if no config is found.
      disable_sdk (bool): This builder will not be using the SDK at all. Only
          for branches with broken or no Build API.
      commit (GitilesCommit): The GitilesCommit for the build, or None.
      targets (list[build_target]): List of build_targets for metadata_json to
          use instead of our build_target.

    Returns:
      BuilderConfig or None, with an active context.
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
      config = self.m.cros_source.configure_builder(commit, changes,
                                                    is_staging=is_staging)
      targets = targets or [self.build_target]
      if changes and config and not config.build.apply_gerrit_changes:
        raise recipe_api.StepFailure(
            'Changes provided, but builder does not apply changes')
      if config and config.id.name and self.build_target.name:
        self.m.cros_bisect.set_bisect_builder(self.build_target.name)
      if config:
        self.m.cros_sdk.set_use_flags(config.build.use_flags)
      if config or missing_ok:
        with self.m.workspace_util.setup_workspace(), \
            _maybe_context(None if disable_sdk
                           else self.m.cros_sdk.cleanup_context):
          with _maybe_context(self.m.metadata_json.context if config else None,
                              config, targets):
            yield config

          # If we have applied patches and the SDK was not validated, then we
          # need to do so before leaving the context.
          if (self._chroot_created and not self._dep_graph and
              self.m.workspace_util.patch_sets):
            self._get_dep_graph([])
      else:
        # No config, and missing_ok is False.
        raise recipe_api.StepFailure('Missing configuration for {}'.format(
            build.builder.builder))

  @contextlib.contextmanager
  def setup_workspace_and_chroot(self, no_chroot_timeout=False):
    """Setup the workspace and chroot for the builder.

    This context manager sets up the workspace path.

    Args:
      no_chroot_timeout (bool): whether to allow unlimited time to create the
          chroot.

    Returns:
      (bool): Whether the build is relevant.
    """
    with self.setup_workspace():
      yield self.setup_chroot(no_chroot_timeout)

  @contextlib.contextmanager
  def setup_workspace(self):
    """Setup the workspace for the builder."""
    # If we do not have a config, use an empty one.
    config = self.config_or_default

    # Set up source checkouts.
    with self.m.workspace_util.sync_to_commit(staging=self.is_staging):

      # Apply any appropriate gerrit changes.
      ignore_missing_projects = (
          config.general.manifest == BuilderConfig.General.PUBLIC)
      self.m.workspace_util.apply_changes(
          ignore_missing_projects=ignore_missing_projects)

      # The Chrome OS verison can be reported once the workspace is synced.
      version = self.m.cros_version.version
      self.m.easy.set_properties_step(chromeos_version=str(version))

      yield

  def setup_chroot(self, no_chroot_timeout=False):
    """Setup the chroot for the builder.

    Args:
      no_chroot_timeout (bool): whether to allow unlimited time to create the
          chroot.

    Returns:
      (bool): Whether the build is relevant.
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
      self.m.cros_sdk.uprev_packages()
      self.m.cros_sdk.create_chroot(
          version=config.general.sdk_cache_version, use_image=self.is_staging,
          timeout_sec=None if config.build.sdk_update.compile_source or
          no_chroot_timeout else 'DEFAULT')
      self._chroot_created = True

      # Avoid passing empty BuildTarget message when we don't have one,
      # e.g. chromite-cq.
      tc_targets = [self.build_target] if self.build_target.name else None
      tc_targets = None if self._force_empty_toolchain_targets else tc_targets
      self.m.cros_sdk.update_chroot(
          self.gitiles_commit, self.gerrit_changes,
          toolchain_targets=tc_targets,
          build_source=config.build.sdk_update.compile_source)

    return relevance != Relevance.POINTLESS

  def setup_sysroot_and_determine_relevance(self, with_sysroot=True,
                                            packages=None):
    """Setup the sysroot for the builder and determine build relevance.

    Args:
      with_sysroot (bool): Whether to create a sysroot.  Default: True.
          (Some builders do not require a sysroot.)
      packages (list[PackageInfo]): Used to override the list of packages.

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
      profile = Profile(name=config.build.portage_profile.profile)
      self._package_indexes = self.m.cros_prebuilts.get_package_index_info(
          config.artifacts.prebuilts_gs_bucket, snapshot=self.gitiles_commit,
          build_target=self.build_target, profile=profile)
      self.m.sysroot_util.create_sysroot(self.build_target, profile,
                                         package_indexes=self._package_indexes)

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

    # TODO(crbug/1081828): After 2020-11-12, if there is no sysroot, that's ok.
    # Note: the dependency graph requires a sysroot prior to
    # crrev.com/c/2197226.
    packages = packages or (self.m.cros_bisect.get_packages() or
                            config.build.install_packages.packages)
    dep_graph = self._get_dep_graph(packages)

    # In the cases where force_relevant is True:
    # 1. input_properties.force_relevant_build is True, and/or
    # 2. output_properties.testing_toolchain is True (now tracked in
    #    cros_relevance), and/or
    # 3. output_properties.artifact_prep is True.
    # 4. The gerrit change contains the appropriate footer.
    force_rel = (
        self._force_relevant_build or
        config.id.name in self.m.cros_relevance.check_force_relevance_footer(
            self.gerrit_changes, [config]))

    pointless = self.m.cros_relevance.is_build_pointless(
        self.gerrit_changes, self.gitiles_commit, dep_graph=dep_graph.target,
        config=self.m.cros_infra_config.config_or_default,
        force_relevant=force_rel)
    if pointless:
      self.m.buildbucket.hide_current_build_in_gerrit()

    return _env_info(pointless, packages)

  def _get_dep_graph(self, packages):
    """Fetch the dependency graph, and validate the SDK for reuse.

    Args:
      packages (list[PackageInfo]): list of packages.  Default is the list for
          this build_target.

    Returns:
      The dependency graph from cros_relevance.get_dependency_graph.
    """
    self._dep_graph = (
        self._dep_graph or self.m.cros_relevance.get_dependency_graph(
            sysroot=self.sysroot, chroot=self.chroot, packages=packages))

    with self.m.step.nest('validate SDK reuse'):
      # If any of the changes affect the sdk, mark the sdk as dirty.
      if self.m.cros_relevance.is_depgraph_affected(
          self.gerrit_changes, self.gitiles_commit,
          dep_graph=self._dep_graph.sdk,
          test_value=self.m.workspace_util.toolchain_cls_applied):
        self.m.cros_sdk.mark_sdk_as_dirty()

    return self.dep_graph

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
                       dryrun=False):
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
          PackageInfo(category='virtual', package_name='implicit-system'))
    if self.m.cros_infra_config.should_run(install_packages.run_spec):
      with self.m.context(env={'DEPOT_TOOLS_COLLECT_METRICS': '0'}):
        self.m.sysroot_util.install_packages(
            config, self.dep_graph, relevant_packages,
            artifact_build=self.artifact_build,
            package_indexes=self._package_indexes, timeout_sec=timeout_sec,
            name=name, dryrun=dryrun)

    return not self.m.cros_infra_config.should_exit(install_packages.run_spec)

  def build_and_test_images(self, config=None, include_version=False):
    """Build the image and run ebuild tests.

    This behavior is adjusted by the run_spec values in config.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      include_version (bool): Whether or not to pass the workspace verson
        to sysroot_util.build.
    Returns:
      (bool): Whether to continue with the build.
    """
    config = config or self.config_or_default
    build_images = config.build.build_images
    unit_tests = config.unit_tests

    builder_path = self.m.cros_artifacts.artifacts_gs_path(
        config.id.name, self.build_target, config.id.type)

    extra_kwargs = {}
    if include_version:
      version = self.m.cros_version.version
      extra_kwargs = {'version': str(version)}

    self.m.sysroot_util.build_images(build_images.image_types, builder_path,
                                     build_images.disable_rootfs_verification,
                                     build_images.disk_layout, **extra_kwargs)

    # If we should run ebuild tests, do that.
    if self.m.cros_infra_config.should_run(unit_tests.ebuilds_run_spec):
      with self.m.step.nest('run ebuild tests') as presentation:
        relevant_testable_packages = unit_tests.packages
        testable_packages_optional = False
        filter_only_cros_workon = False
        if (config.unit_tests.dependencies ==
            BuilderConfig.CL_AFFECTED_DEPENDENCIES):
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
                x for x in self._cl_affected_sysroot_packages
                if PackageInfo(category=x.category, package_name=x.package_name)
                in list(unit_tests.packages)
            ]
        response = self.m.cros_build_api.TestService.BuildTargetUnitTest(
            BuildTargetUnitTestRequest(
                build_target=self.build_target, chroot=self.m.cros_sdk.chroot,
                result_path=str(self.m.path.mkdtemp()),
                package_blocklist=unit_tests.package_blocklist,
                packages=relevant_testable_packages,
                flags=BuildTargetUnitTestRequest.Flags(
                    code_coverage=self._test_with_code_coverage,
                    empty_sysroot=unit_tests.empty_sysroot,
                    testable_packages_optional=testable_packages_optional,
                    filter_only_cros_workon=filter_only_cros_workon)),
            # Asan builders take longer than 2.5 hrs. https://crbug.com/1170372.
            timeout=3 * 60 * 60,
            response_lambda=self.m.cros_build_api.failed_pkg_names)
        self.m.failures.set_failed_packages(presentation,
                                            response.failed_packages)

    return not self.m.cros_infra_config.should_exit(unit_tests.ebuilds_run_spec)

  def upload_artifacts(self, config=None, failing_build=False,
                       private_bundle_func=None, sysroot=None):
    """Upload artifacts from the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      failing_build (bool): whether or not the build is failing, used (in part)
          to decide whether or not to upload artifacts.
      private_bundle_func (func): If a private bundling method is needed (such
          as when there is no Build API on the branch), this will be called
          instead of the internal bundling method.
      sysroot (Sysroot): Use this sysroot.  Defaults to the primary Sysroot for
          the build.

    Returns:
      (UploadedArtifacts) information about uploaded artifacts.
    """
    config = config or self.config_or_default
    sysroot = sysroot or self.sysroot or Sysroot(build_target=self.build_target)

    if self.m.cros_artifacts.has_output_artifacts(
        config.artifacts.artifacts_info):
      return self.m.cros_artifacts.upload_artifacts(
          config.id.name, config.id.type, config.artifacts.artifacts_gs_bucket,
          artifacts_info=config.artifacts.artifacts_info, chroot=self.chroot,
          sysroot=sysroot, failing_build=failing_build,
          private_bundle_func=private_bundle_func)

    if self.m.cros_build_api.has_endpoint(self.m.cros_build_api.TestService,
                                          'BuildTestServiceContainers'):
      with self.m.step.nest(
          'build & upload test service containers') as presentation:
        version = self.m.cros_version.version.legacy_version
        response = self.m.cros_build_api.TestService.BuildTestServiceContainers(
            BuildTestServiceContainersRequest(build_target=self.build_target,
                                              chroot=self.m.cros_sdk.chroot,
                                              version=version),
            timeout=1 * 60 * 60)
        presentation.step_text = (
            'Test containers (gcr.io/chromeos-bot) build/push result for'
            ' %s: %s ' % (version, str(response.results)))
    return {}

  def upload_prebuilts(self, config=None):
    """Upload prebuilts from the build.

    Upload prebuilts if the configuration has uploadable prebuilts.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    config = config or self.config
    artifacts = config.artifacts

    # TODO(crbug/1112425): config.build.portage_profile is migrating.
    profile = Profile(name=config.build.portage_profile.profile)
    if artifacts.prebuilts in self.UPLOADABLE_PREBUILTS:
      self.m.cros_prebuilts.upload_target_prebuilts(
          self.build_target, profile, config.id.type,
          artifacts.prebuilts_gs_bucket,
          private=(artifacts.prebuilts == BuilderConfig.Artifacts.PRIVATE))
