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
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromiumos.common import UseFlag
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
    self._is_slim = False

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
  def is_staging(self):
    return self.m.cros_infra_config.is_staging

  @property
  def sysroot(self):
    return self.m.sysroot_util.sysroot

  @property
  def chroot(self):
    return self.m.cros_sdk.chroot

  @property
  def dep_graph(self):
    return self._dep_graph

  @contextlib.contextmanager
  def configure_builder(self, is_staging=None, missing_ok=False):
    """Initial setup steps for the builder.

    This context manager returns with all of the contexts that an image builder
    needs to have when it runs, for cleanup to happen properly.

    Args:
      is_staging (bool): Whether this is a staging builder.  Use this to
          override auto-detection. By default, anything in the 'staging' bucket
          is considered a staging builder.
      missing_ok (bool): Whether it is OK if no config is found.

    Returns:
      BuilderConfig or None, with an active context.
    """
    with self.m.bot_cost.build_cost_context():
      build = self.m.buildbucket.build
      changes = build.input.gerrit_changes
      self._is_slim = build.builder.builder.endswith('-slim-cq')
      config = self.m.cros_infra_config.configure_builder(
          self.m.buildbucket.gitiles_commit, changes, is_staging=is_staging)
      if (changes and config and not config.build.apply_gerrit_changes):
        raise recipe_api.StepFailure(
            'Changes provided, but builder does not apply changes')
      if config and config.id.name and self.build_target.name:
        self.m.cros_bisect.set_bisect_builder(self.build_target.name)
      if config:
        self.m.cros_sdk.set_use_flags(config.build.use_flags)
      if config or missing_ok:
        with self.m.workspace_util.setup_workspace(), \
            self.m.cros_sdk.cleanup_context():
          if config:
            with self.m.metadata_json.context(config, self.build_target):
              yield config
          else:
            # No config, and missing_ok is true.
            yield None

          # If we have applied patches and the SDK was not validated, then we
          # need to do so before leaving the context.
          if not self._dep_graph and self.m.workspace_util.patch_sets:
            if self._chroot_created:
              self._get_dep_graph([])
      else:
        # No config, and missing_ok is False.
        raise recipe_api.StepFailure('Missing configuration for {}'.format(
            build.builder.builder))

  @contextlib.contextmanager
  def setup_workspace_and_chroot(self, no_chroot_timeout=False):
    """Setup the workspace and chroot for the builder.

    This context manager sets up the workspace path.

    Returns:
      (bool): Whether the build is relevant.
    """
    # If we do not have a config, use an empty one.
    config = self.config_or_default

    # Set up source checkouts.
    with self.m.workspace_util.sync_to_commit(staging=self.is_staging):

      # Apply any appropriate gerrit changes.
      fail_not_applicable = False
      if config.general.manifest == BuilderConfig.General.PUBLIC:
        fail_not_applicable = True
      self.m.workspace_util.apply_changes(
          fail_not_applicable=fail_not_applicable)

      # The Chrome OS verison can be reported once the workspace is synced.
      version = self.m.cros_version.read_workspace_version()
      self.m.easy.set_properties_step(chromeos_version=str(version))

      relevance = Relevance.UNKNOWN
      if self._artifact_build:
        # Early check to see if the build is pointless. (No chroot nor
        # sysroot yet.)
        relevance = self.m.sysroot_util.update_for_artifact_build(
            None, config.artifacts, force_relevance=self._force_relevant_build)

      if not self._artifact_build or relevance != Relevance.POINTLESS:
        self.m.cros_sdk.uprev_packages()
        timeout = None if config.build.sdk_update.compile_source else 'DEFAULT'
        self.m.cros_sdk.create_chroot(
            version=config.general.sdk_cache_version, use_image=self.is_staging,
            timeout_sec=None if config.build.sdk_update.compile_source or
            no_chroot_timeout else 'DEFAULT')
        self._chroot_created = True

        self.m.cros_sdk.update_chroot(
            self.gitiles_commit, self.gerrit_changes,
            toolchain_targets=[self.build_target],
            build_source=config.build.sdk_update.compile_source)

      yield relevance != Relevance.POINTLESS

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
      target_versions = json_format.MessageToDict(
          self.m.cros_build_api.PackageService.GetTargetVersions(
              GetTargetVersionsRequest(chroot=self.m.cros_sdk.chroot,
                                       build_target=self.build_target)),
          including_default_value_fields=True)
      self.m.easy.set_properties_step(target_versions=target_versions)
      if self.m.cros_artifacts.has_output_artifacts(artifacts.artifacts_info):
        self.m.metadata_json.add_version_entries(target_versions)
        self.m.metadata_json.upload_to_gs(config, self.build_target,
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
    pointless = self.m.cros_relevance.is_build_pointless(
        self.gerrit_changes, self.gitiles_commit, dep_graph=dep_graph.target,
        force_relevant=self._force_relevant_build)
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

  def bootstrap_sysroot_and_install_packages(self, config=None, packages=None,
                                             timeout_sec='DEFAULT', name=None):
    """Bootstrap the sysroot and install packages as appropriate.

    The config determines whether to call install packages.  If installing
    packages, fetch Chrome source when needed.

    Args:
      config (BuilderConfig): The Builder Config for the build.
      packages (list[PackageInfo]): list of packages to install.  Default: all
          packages for the build_target.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      name (string): step name for install packages, or None for default.

    Returns:
      (bool): Whether to continue with the build.
    """
    # Make sure we have a valid config
    config = config or self.config_or_default

    self.m.sysroot_util.bootstrap_sysroot(
        compile_source=config.build.install_toolchain.compile_source)

    install_packages = config.build.install_packages
    relevant_packages = packages
    if self._is_slim:
      relevant_packages = self.m.cros_relevance.get_package_dependencies(
          sysroot=self.sysroot, chroot=self.m.cros_sdk.chroot,
          patch_sets=self.m.workspace_util.patch_sets, packages=packages)
    if self.m.cros_infra_config.should_run(install_packages.run_spec):
      # TODO(crbug/1112425): config.build.portage_profile is migrating.
      profile = Profile(name=config.build.portage_profile.profile)
      self.m.sysroot_util.install_packages(
          config, self.dep_graph, relevant_packages,
          artifact_build=self._artifact_build,
          package_indexes=self._package_indexes, timeout_sec=timeout_sec,
          name=name)

    return not self.m.cros_infra_config.should_exit(install_packages.run_spec)

  def build_and_test_images(self, config=None):
    """Build the image and run ebuild tests.

    This behavior is adjusted by the run_spec values in config.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.

    Returns:
      (bool): Whether to continue with the build.
    """
    config = config or self.config_or_default
    build_images = config.build.build_images
    unit_tests = config.unit_tests

    builder_path = self.m.cros_artifacts.artifacts_gs_path(
        config.id.name, self.build_target, config.id.type)

    self.m.sysroot_util.build_images(build_images.image_types, builder_path,
                                     build_images.disable_rootfs_verification,
                                     build_images.disk_layout)

    # If we should run ebuild tests, do that.
    if self.m.cros_infra_config.should_run(unit_tests.ebuilds_run_spec):
      with self.m.step.nest('run ebuild tests') as presentation:
        relevant_testable_packages = unit_tests.packages
        if self._is_slim:
          relevant_testable_packages = self.m.cros_relevance.get_package_dependencies(
              sysroot=self.sysroot, chroot=self.m.cros_sdk.chroot,
              patch_sets=self.m.workspace_util.patch_sets,
              packages=unit_tests.packages)
        response = self.m.cros_build_api.TestService.BuildTargetUnitTest(
            BuildTargetUnitTestRequest(
                build_target=self.build_target, chroot=self.m.cros_sdk.chroot,
                result_path=str(self.m.path.mkdtemp()),
                package_blacklist=unit_tests.package_blacklist,
                packages=relevant_testable_packages,
                flags=BuildTargetUnitTestRequest.Flags(
                    code_coverage=self._test_with_code_coverage,
                    empty_sysroot=unit_tests.empty_sysroot)),
            # Allow 2.5 hours for this step because the change associated with
            # https://bugs.chromium.org/p/chromium/issues/detail?id=1095661#c76
            # dumps additional debug at 2 hours.
            timeout=150 * 60,
            response_lambda=self.m.cros_build_api.failed_pkg_names)
        self.m.failures.set_failed_packages(presentation,
                                            response.failed_packages)
        if self._test_with_code_coverage:
          self.m.code_coverage.process_coverage_data(self.build_target)

    return not self.m.cros_infra_config.should_exit(unit_tests.ebuilds_run_spec)

  def upload_artifacts(self, config=None):
    """Upload artifacts from the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    config = config or self.config_or_default

    if self.m.cros_artifacts.has_output_artifacts(
        config.artifacts.artifacts_info):
      self.m.cros_artifacts.upload_artifacts(
          config.id.name, self.build_target, config.id.type,
          config.artifacts.artifacts_gs_bucket, sysroot=self.sysroot,
          chroot=self.chroot, artifacts_info=config.artifacts.artifacts_info)

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

  def sign_images(self, config=None):
    """Sign the uploaded images.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    with self.m.step.nest('sign images'):
      # TODO: implement me!
      pass

  def generate_payloads(self, config=None):
    """Generate release payloads for the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    with self.m.step.nest('generate payloads'):
      # TODO: implement me!
      pass
