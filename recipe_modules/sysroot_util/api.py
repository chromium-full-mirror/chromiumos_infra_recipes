# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

import re
from typing import Iterable, List, Optional

from google.protobuf import json_format

from PB.chromite.api.artifacts import BuildSetupResponse
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import CreateImageResult
from PB.chromite.api.image import CreateNetbootRequest
from PB.chromite.api.image import Image
from PB.chromite.api.image import TestImageRequest
from PB.chromite.api.sdk import CleanRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import Profile as OldProfile
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import SysrootCreateResponse
from PB.chromiumos import builder_config as builder_config_pb2
from PB.chromiumos import common as common_pb2
from PB.chromiumos import prebuilts_cloud as prebuilts_cloud_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from recipe_engine import recipe_api


class SysrootUtilApi(recipe_api.RecipeApi):
  """A module for sysroot setup, manipulation, and use."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._disable_chrome_source_purge = properties.disable_chrome_source_purge

  def initialize(self):
    self._sysroot = None

  @property
  def sysroot(self):
    return self._sysroot

  def _image_type_to_fname(self, image_type):
    """Strip the IMAGE_TYPE_ prefix and provide a string image path."""
    rep_name = re.sub('^IMAGE_TYPE_', '', common_pb2.ImageType.Name(image_type))
    return '/build/images/%s.bin' % rep_name.lower()

  def update_for_artifact_build(self, chroot, artifacts, force_relevance=False,
                                test_data=None, name=None):
    """Update ebuilds for artifact build.

    Args:
      chroot (Chroot): Chroot, or None.
      artifacts (BuilderConfig.Artifacts): Artifact Information
      force_relevance (bool): Whether to always claim relevant.
      test_data (str): test response (JSON) from the
        ArtifactsService/BuildSetup call, or None.
      name (str): Step name to use, or None for default name.

    Returns:
      (BuildSetupResponse): Whether the build is relevant.
    """
    # Prepare for the build.  If the build is pointless, we are done.
    resp = self.m.cros_artifacts.prepare_for_build(chroot, self.sysroot,
                                                   artifacts.artifacts_info,
                                                   force_relevance,
                                                   test_data=test_data,
                                                   name=name)

    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # BuildSetup endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no BuildSetup endpoint
    # defined, then resp will be UNKNOWN.
    return BuildSetupResponse.NEEDED if force_relevance else resp

  def create_sysroot(self, build_target, profile=None, chroot_current=True,
                     replace=True, package_indexes=None, timeout_sec='DEFAULT',
                     use_cq_prebuilts: bool = False, test_data=None, name=None):
    """Create the sysroot.

    Args:
      build_target (BuildTarget): Which build_target to create a sysroot for.
      profile (chromiumos.Profile): The profile the sysroot is to use, or None.
      chroot_current (bool): Whether the chroot is current.  (If not, it will be
        updated.
      replace (bool): Whether to replace an existing sysroot.
      package_indexes (list[PackageIndexInfo]): Package indexes to use, or None.
      timeout_sec (int): Step timeout (in seconds).  Default: None if a
        toolchain change is detected, otherwise 10 minutes.
      use_cq_prebuilts (bool): Whether to use CQ prebuilts.
      test_data (str): test response (JSON) from the SysrootService/Create
        call, or None to generate a default response based on the input data.
      name (str): Step name to use, or None for the default name.

    Returns:
      Sysroot
    """
    package_indexes = package_indexes or []
    test_data = test_data or json_format.MessageToJson(
        SysrootCreateResponse(
            sysroot=Sysroot(path='/build/%s' %
                            build_target.name, build_target=build_target)))
    if timeout_sec == 'DEFAULT':
      timeout_sec = None if self.m.cros_sdk.long_timeouts else 10 * 60

    toolchain_cls = self.m.workspace_util.toolchain_cls_applied
    with self.m.step.nest(name or 'create sysroot') as pres:
      if self.m.cros_sdk.force_off_toolchain_changed:
        pres.step_text = 'Forcing toolchain_changed=False'
        toolchain_cls = False
      # TODO(crbug/1112425): config.build.portage_profile is migrating.
      profile = (
          OldProfile(name=profile.name) if profile and profile.name else None)
      flags = SysrootCreateRequest.Flags(chroot_current=chroot_current,
                                         replace=replace,
                                         toolchain_changed=toolchain_cls,
                                         use_cq_prebuilts=use_cq_prebuilts)
      create_sysroot_response = self.m.cros_build_api.SysrootService.Create(
          SysrootCreateRequest(build_target=build_target, profile=profile,
                               chroot=self.m.cros_sdk.chroot, flags=flags,
                               package_indexes=package_indexes),
          timeout=timeout_sec, test_output_data=test_data)
      self._sysroot = create_sysroot_response.sysroot
      return self.sysroot

  def bootstrap_sysroot(self, compile_source=False, response_lambda=None,
                        timeout_sec='DEFAULT', test_data=None, name=None):
    """Bootstrap the sysroot by calling InstallToolchain.

    Args:
      compile_source (bool): Whether to compile from source.
      response_lambda (fn(output_proto)->str): A function that appends a string
        to the build api response step. Used to make failure step names unique
        across differing root causes.  Default:
        cros_build_api.failed_pkg_data_names.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      test_data (str): test response (JSON) from the
        SysrootService/InstallToolchain call, or None to use the default in
        cros_build_api/test_api.py.
      name (str): Step name to use, or None for the default name.
    """
    # If no timeout was given, it is either unlimited, or 30 minutes.
    if timeout_sec == 'DEFAULT':
      timeout_sec = None if self.m.cros_sdk.long_timeouts else 30 * 60
    response_lambda = response_lambda or self.m.cros_build_api.failed_pkg_data_names

    with self.m.step.nest(name or 'install toolchain') as pres:
      toolchain_cls = self.m.workspace_util.toolchain_cls_applied
      if self.m.cros_sdk.force_off_toolchain_changed:
        pres.step_text = 'Forcing toolchain_changed=False'
        toolchain_cls = False

      flags = InstallToolchainRequest.Flags(compile_source=compile_source,
                                            toolchain_changed=toolchain_cls)
      request = InstallToolchainRequest(
          sysroot=self.sysroot, chroot=self.m.cros_sdk.chroot, flags=flags,
          result_path=common_pb2.ResultPath(
              path=common_pb2.Path(
                  path=str(self.m.path.mkdtemp()),
                  location=common_pb2.Path.OUTSIDE)))
      response = self.m.cros_build_api.SysrootService.InstallToolchain(
          request, response_lambda=response_lambda, timeout=timeout_sec,
          test_output_data=test_data)
      pkgs = self.m.cros_build_api.failed_pkg_logs(request, response)
      self.m.failures.set_compile_failed_packages(pres, pkgs)

  def install_packages(self, config, dep_graph, packages=None,
                       artifact_build=False, package_indexes=None,
                       timeout_sec='DEFAULT', name=None, dryrun=False):
    """Install packages (possibly fetching Chrome source).

    Args:
      config (BuilderConfig): The builder config.
      dep_graph: The dependency graph from cros_relevance.get_dependency_graph.
      packages (list[PackageInfo]): list of packages to install.  Default: all
        packages for the build_target.
      artifact_build (bool): Whether to call update_for_artifact_build.
      package_indexes (list[PackageIndexInfo]): Package indexes to use, or None.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      name (str): Step name to use, or None for default name.
      dryrun (bool): Whether to dryrun the step such that we calculate the
        packages which would have been built, but do not install them.
    """
    packages = packages or []
    package_indexes = package_indexes or []
    install_packages = config.build.install_packages
    skip_clean_package_dirs = install_packages.skip_clean_package_dirs

    bazel_build = (
        install_packages.install_packages_orchestrator ==
        builder_config_pb2.BuilderConfig.BAZEL)
    bazel_targets = (
        InstallPackagesRequest.BazelTargets.LITE
        if install_packages.bazel_targets
        == builder_config_pb2.BuilderConfig.LITE else None)

    name = name or 'install packages'
    if timeout_sec == 'DEFAULT':
      default_timeout_hours = 12 if bazel_build else 8
      timeout_sec = (None if self.m.cros_sdk.long_timeouts else
                     default_timeout_hours * 60 * 60)

    with self.m.step.nest(name) as presentation:
      toolchain_cls = self.m.workspace_util.toolchain_cls_applied
      if self.m.cros_sdk.force_off_toolchain_changed:
        presentation.step_text = 'Forcing toolchain_changed=False'
        toolchain_cls = False

      def _InstallPackagesRequest(dryrun=False):
        """Helper to make InstallPackagesRequest."""
        remoteexec_config = None
        if self.m.remoteexec.enable_logs_upload:
          remoteexec_config = common_pb2.RemoteexecConfig(
              log_dir=common_pb2.SyncedDir(
                  dir=str(self.m.path.mkdtemp(prefix='remoteexec-logs-'))))

        snapshot_shas = self.m.cros_source.fetch_snapshot_shas(count=5)
        is_private = config.artifacts.prebuilts == builder_config_pb2.BuilderConfig.Artifacts.PRIVATE

        return InstallPackagesRequest(
            chroot=self.m.cros_sdk.chroot, sysroot=self.sysroot,
            packages=packages, package_indexes=package_indexes,
            flags=InstallPackagesRequest.Flags(
                compile_source=install_packages.compile_source,
                use_goma=self.m.cros_sdk.has_goma_config(),
                toolchain_changed=toolchain_cls, dryrun=dryrun,
                bazel=bazel_build,
                skip_clean_package_dirs=skip_clean_package_dirs),
            use_flags=config.build.use_flags,
            goma_config=self.m.cros_sdk.goma_config(),
            remoteexec_config=remoteexec_config,
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=str(self.m.path.mkdtemp()),
                    location=common_pb2.Path.OUTSIDE)),
            bazel_targets=bazel_targets,
            binhost_lookup_service_data=prebuilts_cloud_pb2
            .BinhostLookupServiceData(snapshot_shas=snapshot_shas,
                                      private=is_private))

      chrome_root = None
      with self.m.step.nest('check chrome source needed') as check_pres:
        # Block and wait for the chrome checkout of main.
        self.m.chrome.wait_for_sync_chrome_source_async()
        ebuild_chrome = self.m.chrome.needs_chrome_source(
            _InstallPackagesRequest(), dep_graph, check_pres)

        if ebuild_chrome:
          # Bazel builds pull the source in a repository rule, so don't need the
          # recipe to pull it or update the SDK accordingly.
          if not bazel_build:
            # This will change the return from _InstallPackagesRequest().
            chrome_root = self.m.path['start_dir'].join('chrome')
            self.m.chrome.cache_sync(cache_path=chrome_root, sync=False,
                                     step_name='populate chrome cache')
            self.m.chrome.sync(chrome_root, self.m.cros_sdk.chroot,
                               self.sysroot.build_target,
                               config.chrome.internal,
                               cache_dir=chrome_root.join('chrome_cache'))
            self.m.cros_sdk.set_chrome_root(chrome_root)

          if install_packages.use_remoteexec:
            self.m.cros_sdk.configure_remoteexec()
          elif not install_packages.disable_goma:
            self.m.cros_sdk.configure_goma()
        elif ('chromeos.build_menu.chrome_sync'
              in self.m.cros_infra_config.experiments):
          # Since we don't need chrome source, delete the checkout.
          self.m.chrome.delete_chrome_checkout()

      if self.m.cq.active:
        self.m.android.uprev_if_unstable_ebuild_changed(
            chroot=self.m.cros_sdk.chroot, sysroot=self.sysroot,
            patch_sets=self.m.workspace_util.patch_sets)

      # Final round of preparation to build artifacts.  Some artifacts need
      # to use portage (or a chroot and/or sysroot) in order to fully prepare,
      # so they have to finish preparation inside the SDK.
      #
      # We don't care what the return value is, since we're committed to
      # running at least install packages at this point.  Let the module know
      # that we are forcing relevance.
      if artifact_build:
        self.m.sysroot_util.update_for_artifact_build(
            self.m.cros_sdk.chroot, config.artifacts, force_relevance=True,
            name='prepare artifacts final')
      install_pkg_request = _InstallPackagesRequest(dryrun=dryrun)
      response = self.m.cros_build_api.SysrootService.InstallPackages(
          install_pkg_request,
          response_lambda=self.m.cros_build_api.failed_pkg_data_names,
          pkg_logs_lambda=self.m.cros_build_api.failed_pkg_logs,
          timeout=timeout_sec)

      # Remove ~60-100GB of chrome incremental build artifacts.
      if ('chromeos.sysroot_util.clean_incrementals'
          in self.m.cros_infra_config.experiments):
        if ebuild_chrome:
          clean_request = CleanRequest(incrementals=True)
          _ = self.m.cros_build_api.SdkService.Clean(clean_request)

      # Process goma response to upload logs, stats, and counterz.
      if self.m.cros_sdk.has_goma_config():
        self.m.goma.process_artifacts(
            response, install_pkg_request.goma_config.log_dir.dir,
            self.sysroot.build_target.name, self.m.cros_infra_config.is_staging)

      if self.m.remoteexec.enable_logs_upload:
        with self.m.step.nest('process reclient artifacts'):
          self.m.remoteexec.process_artifacts(
              response,
              install_pkg_request.remoteexec_config.log_dir.dir,
              self.sysroot.build_target.name,
              self.m.cros_infra_config.is_staging,
          )

      pkgs = self.m.cros_build_api.failed_pkg_logs(install_pkg_request,
                                                   response)
      # If we have a chrome checkout and the prop to disable cleanup is not off,
      # clean up the chrome cache checkout.
      if (chrome_root and not self._disable_chrome_source_purge):
        self.m.file.rmtree('deleting chrome checkout', chrome_root)
        # Set the chrome root to None so it isn't used later.
        self.m.cros_sdk.set_chrome_root(None)
      self.m.failures.set_compile_failed_packages(presentation, pkgs)

  def create_netboot_image(self) -> None:
    """Create a netboot image for the factory build."""

    if self.m.cros_build_api.has_endpoint(self.m.cros_build_api.ImageService,
                                          'CreateNetboot'):
      request = CreateNetbootRequest(chroot=self.m.cros_sdk.chroot,
                                     build_target=self.sysroot.build_target,
                                     factory_shim_path='')
      _ = self.m.cros_build_api.ImageService.CreateNetboot(request)
    else:
      # Old factory branches do not have the CreateNetboot endpoint, so we
      # have replicated the underlying functionality here. This will no longer
      # be needed once all branches are past 15196.B.

      board = self.sysroot.build_target.name

      # These path parts were created by manually evaluating the code in
      # CreateNetboot and hard-coding the current values.
      scripts_dir = self.m.src_state.workspace_path.join('src/scripts')
      image_dir = f'/mnt/host/source/src/build/images/{board}/factory_shim'

      with self.m.context(cwd=scripts_dir):
        self.m.step('Running `make_netboot.sh` for legacy factory branch', [
            './make_netboot.sh', f'--board={board}', f'--image_dir={image_dir}'
        ])

  def build_images(self, image_types: List['common_pb2.ImageType'],
                   builder_path: str, disable_rootfs_verification: bool,
                   disk_layout: str, base_is_recovery: bool = False,
                   version: Optional[str] = None,
                   timeout_sec: Optional[int] = None,
                   build_test_data: Optional[str] = None,
                   test_test_data: Optional[str] = None,
                   name: Optional[str] = None, skip_image_tests: bool = False,
                   verify_image_size_delta: bool = False,
                   bazel: bool = False) -> Iterable[Image]:
    """Build and validate images.

    Args:
      image_types: Image types to build.
      builder_path: Builder path in GS for artifacts.
      disable_rootfs_verification: whether to disable rootfs verification.
      disk_layout: disk_layout to set, or empty for default.
      base_is_recovery: copy the base image to recovery_image.bin.
      version: version string to pass to build API, or None.
      timeout_sec: Step timeout (in seconds), None uses default timeout.
      build_test_data: test response (JSON) from the ImageService/Create call,
        call, or None.
      test_test_data: test response (JSON) from the ImageService/Test call, or
        None.
      name: Step name to use, or None for default name.
      skip_image_tests: Whether to skip tests of the built image via
        ImageService/Test.
      verify_image_size_delta: Whether to verify the image size delta.
      bazel: Whether to use Bazel to build the images.

    Returns:
      The images built during the stage.
    """
    if not image_types:
      return None

    if common_pb2.IMAGE_TYPE_FACTORY in image_types:
      # Factory branches before 14909 are raising a permission error when
      # writing to /tmp within the chroot, so we'll force the write permission.
      # Also, we don't have a good way to test when a path does not exist. See:
      # http://cs/f:infra%2Frecipes%20path%5C.exists.*pragma
      # NB: this path construction is a hack and should be removed.
      chroot_tmp_path = self.m.src_state.workspace_path.join('chroot/tmp')
      if self.m.path.exists(chroot_tmp_path):  # pragma: nocover
        chmod_cmd = [
            'sudo', '-n', 'chmod', '-R', 'u=rwx,g=rwx,o=rwx,-t', chroot_tmp_path
        ]
        self.m.step('changing permissions of %s' % chroot_tmp_path, chmod_cmd,
                    infra_step=True)

    build_test_data = build_test_data or json_format.MessageToJson(
        CreateImageResult(
            success=True, images=[
                Image(
                    type=x, path=str(self.m.path['start_dir'].join(
                        self._image_type_to_fname(x))),
                    build_target=self.sysroot.build_target) for x in image_types
            ]))
    with self.m.step.nest(name or 'build images') as pres:
      # Use default timeout if none specified.
      if not timeout_sec:
        timeout_sec = 2 * 60 * 60
      request = CreateImageRequest(
          build_target=self.sysroot.build_target,
          chroot=self.m.cros_sdk.chroot,
          image_types=image_types,
          builder_path=builder_path,
          disable_rootfs_verification=disable_rootfs_verification,
          disk_layout=disk_layout,
          base_is_recovery=base_is_recovery,
          version=version,
          bazel=bazel,
      )
      response = self.m.cros_build_api.ImageService.Create(
          request, timeout=timeout_sec,
          response_lambda=self.m.cros_build_api.failed_pkg_names,
          test_output_data=build_test_data)
      self.m.failures.set_compile_failed_packages(
          pres, [(p, '') for p in response.failed_packages])

      # b/239795601: We can't currently finish the factory image inside of the
      # previous Create call because the image doesn't have network access and
      # packages are attempting downloads when we're adding the netbook kernel.
      # In the future this should be rolled into the Create() call above.
      if common_pb2.IMAGE_TYPE_FACTORY in image_types:
        self.create_netboot_image()

      # Hack warning. Add the rootfs size to the output properties to make
      # image size regressions easy to calculate until we have the proper
      # system in place.
      rootfs_size = 0
      for event in response.events:
        if event.name.endswith('total_size.base.rootfs'):
          rootfs_size = event.gauge
          break
      self.m.easy.set_properties_step(rootfs_size=rootfs_size)

      if verify_image_size_delta:
        # Use the rootfs size output property from the latest successful
        # postsubmit builder as the base for the comparison.
        with self.m.step.nest('image size regression check') as presentation:
          if not rootfs_size:
            presentation.step_text = 'No rootfs size found for current build.'
          else:
            with self.m.step.nest('fetch last recorded rootfs size') as subpres:
              bbid, latest_size = self._get_last_postsubmit_rootfs_size()
              subpres.step_text = 'build {}: {}B'.format(bbid, latest_size)
            if not latest_size:
              presentation.step_text = 'No previous rootfs size found.'
            else:
              delta = int(rootfs_size) - int(latest_size)
              self.m.easy.set_properties_step(rootfs_delta=delta)
              if delta == 0:
                presentation.step_text = 'No rootfs size delta.'
              else:
                direction = 'increase' if delta > 0 else 'decrease'
                hr_delta = format_size(abs(delta))
                presentation.step_text = \
                  'Estimated {} rootfs size {}.'.format(hr_delta, direction)

      to_test = [
          image for image in response.images
          if image.type == common_pb2.IMAGE_TYPE_BASE
      ]
      if common_pb2.IMAGE_TYPE_BASE not in image_types or not to_test:
        # For now, as in legacy CQ, we only test base images. Images created
        # as a sideeffect (not explicitly requested in image_types) are not
        # tested.
        return response.images

      with self.m.step.nest('test images') as presentation:
        if skip_image_tests:
          presentation.step_text = \
            'Skipping image tests as per board configuration.To check ' \
            'configuration, view generated/builder_configs.cfg or ' \
            'builderconfig/unit_tests_config.star in infra/config.'
          return response.images

        failed_images = []
        for image in to_test:
          result_dir = self.m.path.mkdtemp(prefix='image-test-result-')
          if not self.m.cros_build_api.ImageService.Test(
              TestImageRequest(
                  image=image, build_target=self.sysroot.build_target,
                  result=TestImageRequest.Result(directory=str(result_dir)),
                  chroot=self.m.cros_sdk.chroot),
              test_output_data=test_test_data).success:
            failed_images.append(image)
          self.m.failures.raise_failed_image_tests(failed_images)
      return response.images

  def _get_last_postsubmit_rootfs_size(self):
    builder_name = '{}-postsubmit'.format(self.sysroot.build_target.name)
    fields = frozenset({'id', 'output.properties'})
    predicate = builds_service_pb2.BuildPredicate(
        builder=builder_common_pb2.BuilderID(project='chromeos',
                                             bucket='postsubmit',
                                             builder=builder_name),
        tags=self.m.buildbucket.tags(relevance='relevant'), status='SUCCESS')
    result = self.m.buildbucket.search(predicate, limit=1, fields=fields)

    if result:
      bid = result[0].id
      props = result[0].output.properties
      size = int(props['rootfs_size']) if 'rootfs_size' in props else 0
      return bid, size

    return None, 0


def format_size(bytesize):
  """Convert bytes to human-readable format."""
  if bytesize < 1024:
    return '{}B'.format(bytesize)

  for suffix in 'BKMGTPEZY':
    if bytesize < 1024:
      break
    bytesize /= 1024

  return '{:.1f}{}iB'.format(bytesize, suffix)  # pylint: disable=undefined-loop-variable
