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
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.builder_config import BuilderConfig


class BuildMenuApi(recipe_api.RecipeApi):
  """A module with steps used by image builders.

  Image builders do not call other recipe modules directly: they always get
  there via this module, and be a simple sequence of steps.
  """

  # TODO(crbug/1053703): Make the above statement true.

  UPLOADABLE_PREBUILTS = [
      BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
  ]

  def initialize(self):
    self._dep_graph = None

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
  def configure_builder(self, build_target, is_staging=False, missing_ok=False):
    """Initial setup steps for the builder.

    This context manager returns with all of the contexts that build_target
    needs to have when it runs, for cleanup to happen properly.

    Args:
      build_target (BuildTarget): build_target for the build, or None if the
          builder is build_target agnostic.
      is_staging (bool): Whether this is definitely a staging builder.  By
          default, anything in the 'staging' bucket is considered a staging
          builder.  Use this to cause other builders to be considered staging.
      missing_ok (bool): Whether it is OK if no config is found.

    Returns:
      BuilderConfig or None, with an active context.
    """
    self.build_target = build_target or BuildTarget()
    with self.m.bot_cost.build_cost_context():
      config = self.m.cros_infra_config.configure_builder(
          self.m.buildbucket.gitiles_commit,
          self.m.buildbucket.build.input.gerrit_changes, is_staging=is_staging)
      if config and config.id.name and self.build_target.name:
        self.m.cros_bisect.set_bisect_builder(build_target.name)
      if config:
        self.m.cros_sdk.set_use_flags(config.build.use_flags)
      if config or missing_ok:
        with self.m.workspace_util.setup_workspace(), \
            self.m.cros_sdk.cleanup_context():
          if config:
            with self.m.metadata_json.context(config, build_target):
              yield config
          else:
            # No config, and missing_ok is true.
            yield None

          # If we have applied patches and the SDK was not validated, then we
          # need to do so before leaving the context.
          if not self._dep_graph and self.m.workspace_util.patch_sets:
            self._get_dep_graph([])
      else:
        # No config, and missing_ok is False.
        raise self.m.step.StepFailure('Missing configuration for {}'.format(
            self.m.buildbucket.build.builder.builder))

  def setup_workspace_and_chroot(self, artifact_build=False,
                                 forced_relevant=False):
    """Setup the workspace and chroot for the builder.

    Args:
      artifact_build (bool): Whether to call update_for_artifact_build and
          terminate early if POINTLESS.
      forced_relevant (bool): Whether to force relevance for artifact_builds.

    Returns:
      (bool): Whether the build is relevant.
    """
    self._artifact_build = artifact_build
    self._forced_relevant = forced_relevant

    # If we do not have a config, use an empty one.
    config = self.config_or_default

    # Set up source checkouts.
    self.m.workspace_util.sync_to_commit(staging=self.is_staging)

    # Apply any appropriate gerrit changes.
    self.m.workspace_util.apply_changes()

    # The Chrome OS verison can be reported once the workspace is synced.
    version = self.m.cros_version.read_workspace_version()
    self.m.easy.set_property_step('chromeos_version', str(version))

    relevance = Relevance.UNKNOWN
    if artifact_build:
      # Early check to see if the build is pointless. (No chroot nor
      # sysroot yet.)
      relevance = self.m.sysroot_util.update_for_artifact_build(
          None, config.artifacts, force_relevance=forced_relevant)

    if not artifact_build or relevance != Relevance.POINTLESS:
      # We can only uprev packages if we have a build_target.
      if self.build_target.name:
        self.m.cros_sdk.uprev_packages(build_targets=[self.build_target])
      timeout = None if config.build.sdk_update.compile_source else 'DEFAULT'
      self.m.cros_sdk.create_chroot(
          version=config.general.sdk_cache_version, use_image=self.is_staging,
          timeout_sec=None
          if config.build.sdk_update.compile_source else 'DEFAULT')

      self.m.cros_sdk.update_chroot(
          self.gitiles_commit, self.gerrit_changes,
          toolchain_targets=[self.build_target],
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
      self.m.sysroot_util.create_sysroot(self.build_target,
                                         config.build.portage_profile.profile)

      # Set the target_versions output property, and upload metatdata.
      # This requires a sysroot for at least the package versions.
      target_versions = json_format.MessageToDict(
          self.m.cros_build_api.PackageService.GetTargetVersions(
              GetTargetVersionsRequest(chroot=self.m.cros_sdk.chroot,
                                       build_target=self.build_target)),
          including_default_value_fields=True)
      self.m.easy.set_property_step('target_versions', target_versions)
      if self.m.cros_artifacts.has_output_artifacts(artifacts.artifacts_info):
        self.m.metadata_json.add_version_entries(target_versions)
        self.m.metadata_json.upload_to_gs(config, self.build_target,
                                          partial=True)

    # TODO(crbug/1053703): After 2020-11-12, if there is no sysroot, that's ok.
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
        force_relevant=self._forced_relevant)
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
                                             artifact_build=None,
                                             timeout_sec='DEFAULT', name=None):
    """Install packages (possibly fetching Chrome source).

    Args:
      config (BuilderConfig): The Builder Config for the build.
      packages (list[PackageInfo]): list of packages to install.  Default: all
          packages for the build_target.
      artifact_build (bool): Whether to call update_for_artifact_build.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      name (string): step name for install packages, or None for default.
    """
    # Make sure we have a valid config
    config = config or self.config_or_default

    self.m.sysroot_util.bootstrap_sysroot(
        compile_source=config.build.install_toolchain.compile_source)

    install_packages = config.build.install_packages
    self.m.sysroot_util.install_packages(config, self.dep_graph, packages,
                                         artifact_build=artifact_build,
                                         timeout_sec=timeout_sec, name=name)

  def build_and_test_images(self, config=None, run_tests=True):
    """Build the image and optionally run ebuild tests.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
      run_tests (bool): Whether to run ebuild tests.
    """
    config = config or self.config_or_default
    build_images = config.build.build_images
    unit_tests = config.unit_tests

    builder_path = self.m.cros_artifacts.artifacts_gs_path(
        config.id.name, self.build_target, config.id.type)
    self.m.sysroot_util.build_images(build_images.image_types, builder_path,
                                     build_images.disable_rootfs_verification,
                                     build_images.disk_layout)

    if run_tests:
      with self.m.step.nest('run ebuild tests') as presentation:
        response = self.m.cros_build_api.TestService.BuildTargetUnitTest(
            BuildTargetUnitTestRequest(
                build_target=self.build_target, chroot=self.m.cros_sdk.chroot,
                result_path=str(self.m.path.mkdtemp()),
                package_blacklist=unit_tests.package_blacklist,
                flags=BuildTargetUnitTestRequest.Flags(
                    empty_sysroot=unit_tests.empty_sysroot)),
            timeout=2 * 60 * 60,
            response_lambda=self.m.cros_build_api.failed_pkg_names)
        self.m.failures.set_failed_packages(presentation,
                                            response.failed_packages)

  def upload_artifacts(self, config=None):
    """Upload artifacts from the build.

    Args:
      config (BuilderConfig): The Builder Config for the build, or None.
    """
    config = config or self.config_or_default

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

    if artifacts.prebuilts in self.UPLOADABLE_PREBUILTS:
      self.m.cros_prebuilts.upload_target_prebuilts(
          self.build_target, config.id.type, artifacts.prebuilts_gs_bucket,
          private=(artifacts.prebuilts == BuilderConfig.Artifacts.PRIVATE))
