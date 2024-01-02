# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

import collections
import time
from typing import Dict, List, Optional, Tuple

from google.protobuf import json_format

from PB.chromite.api import artifacts
from PB.chromite.api import firmware
from PB.chromite.api import toolchain
from PB.chromite.api.image import PushImageRequest
from PB.chromiumos import common as common_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService

from recipe_engine import config_types
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

# The base image tar filename, used for generating provenance.
BASE_IMAGE_TAR = 'chromiumos_base_image.tar.xz'
# The recovery image tar filename, used for generating provenance.
RECOVERY_IMAGE_TAR = 'recovery_image.tar.xz'

# TODO(crbug.com/1034529): Migrate these legacy artifacts to new endpoints in
# the appropriate services.

# Maps artifact type to corresponding build API endpoint.
# Note for maintainers: this dictionary must be kept in sync
# with the Starlark config.
_LEGACY_ENDPOINTS_BY_ARTIFACT = {
    BuilderConfig.Artifacts.IMAGE_ZIP: 'BundleImageZip',
    BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD: 'BundleTestUpdatePayloads',
    BuilderConfig.Artifacts.AUTOTEST_FILES: 'BundleAutotestFiles',
    BuilderConfig.Artifacts.TAST_FILES: 'BundleTastFiles',
    BuilderConfig.Artifacts.PINNED_GUEST_IMAGES: 'BundlePinnedGuestImages',
    BuilderConfig.Artifacts.FIRMWARE: 'BundleFirmware',
    BuilderConfig.Artifacts.EBUILD_LOGS: 'BundleEbuildLogs',
    BuilderConfig.Artifacts.CHROMEOS_CONFIG: 'BundleChromeOSConfig',
    BuilderConfig.Artifacts.IMAGE_ARCHIVES: 'BundleImageArchives',
    BuilderConfig.Artifacts.FPMCU_UNITTESTS: 'BundleFpmcuUnittests',
    BuilderConfig.Artifacts.GCE_TARBALL: 'BundleGceTarball',
    BuilderConfig.Artifacts.DEBUG_SYMBOLS: 'BundleDebugSymbols',
}

# The default number of concurrent artifact bundling calls to be made if not set
# by input properties. The current default is to bundle artifacts one at a time.
_DEFAULT_MAX_CONCURRENT_BUNDLING_REQUESTS = 1


class UploadedArtifacts(
    collections.namedtuple('UploadedArtifacts',
                           'gs_bucket gs_path files_by_artifact')):
  __slots__ = ()

  def union(self, other):
    """Union the files_by_artifact in other into self.

    gs_bucket and gs_path must be the same.

    Keys (i.e. artifact types) in files_by_artifacts are unioned. If both self
    and other have the same key, the values (i.e. files) are unioned.

    Args:
      other: Another UploadedArtifacts.

    Returns:
      A unioned UploadedArtifacts.
    """
    assert self.gs_bucket == other.gs_bucket, f'{self.gs_bucket} != {other.gs_bucket}'
    assert self.gs_path == other.gs_path, f'{self.gs_path} != {other.gs_path}'
    value = lambda inst, key: inst.files_by_artifact.get(key, [])
    keys = set(self.files_by_artifact.keys()) | set(
        other.files_by_artifact.keys())

    result = {
        k: sorted(set(value(self, k) + value(other, k))) for k in sorted(keys)
    }

    return UploadedArtifacts(self.gs_bucket, self.gs_path, result)


class CrosArtifactsApi(recipe_api.RecipeApi):
  """A module for bundling and uploading build artifacts."""

  UploadedArtifacts = UploadedArtifacts

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._max_concurrent_bundling_requests = (
        props.max_concurrent_bundling_requests or
        _DEFAULT_MAX_CONCURRENT_BUNDLING_REQUESTS)

    self._gs_upload_path = props.gs_upload_path
    self._skip_publish = props.skip_publish
    self._timestamp_micros = int(time.time() * 1000)

  @property
  def timestamp_micros(self):
    """Return the value of {time} in GS templates."""
    return str(self._timestamp_micros)

  @property
  def gs_upload_path(self):
    """Return the gs upload path, if one was set in properties."""
    return self._gs_upload_path or None

  @property
  def skip_publish(self):
    """Return whether to skip publish, if set in properties."""
    return self._skip_publish or False

  def _get_legacy_endpoint(self, artifact):
    """Return the callable endpoint in ArtifactsService for this artifact.

    Args:
      artifact (ArtifactTypes): The artifact type to bundle.

    Returns:
      callable: The ArtifactsService endpoint.
    """
    assert artifact in _LEGACY_ENDPOINTS_BY_ARTIFACT, (
        'Could not find build API endpoint for bundling artifact %s. '
        'You may need to sync the cros_artifacts recipe endpoint dictionary '
        'with the current build config.' %
        BuilderConfig.Artifacts.ArtifactTypes.Name(artifact))
    name = _LEGACY_ENDPOINTS_BY_ARTIFACT[artifact]
    service = self.m.cros_build_api.ArtifactsService
    return (getattr(service, name) if self.m.cros_build_api.has_endpoint(
        service, name) else None)

  def _bundle_legacy_artifacts(self, chroot, sysroot, path, artifact_types,
                               semaphore):
    """Bundle legacy artifacts.

    Batch handler for legacy artifact types.

    Args:
      chroot (Chroot): The chroot to use.
      sysroot (Sysroot): The sysroot to use.
      path (Path): Path to write bundled artifacts to.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
          artifact bundling calls.

    Returns:
      futures (list[Future]): A list of futures that call the legacy
          ArtifactsService/Bundle Build API endpoint for each configured
          artifact type.
    """

    def _bundle_legacy_artifact(artifact):
      files_by_artifact = {}
      with semaphore:
        name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
        with self.m.step.nest('bundle %s for upload' % name):
          endpoint = self._get_legacy_endpoint(artifact)
          response = artifacts.BundleResponse()
          if endpoint:
            request = artifacts.BundleRequest(
                chroot=chroot, sysroot=sysroot,
                build_target=sysroot.build_target, output_dir=str(path),
                result_path=self._result_path(path))
            response = endpoint(request, infra_step=True)

          files_by_artifact[name] = [
              str(art.artifact_path.path) or art.path
              for art in response.artifacts
          ]
      return files_by_artifact

    futures = []
    for artifact in artifact_types:
      futures.append(self.m.futures.spawn(_bundle_legacy_artifact, artifact))
    return futures

  def _bundle_infra_artifacts(
      self, chroot: common_pb2.Chroot, sysroot: ArtifactsByService.Sysroot,
      outpath: config_types.Path,
      artifact_types: List['BuilderConfig.Artifacts.ArtifactTypes'],
      artifact_profile_info: common_pb2.ArtifactProfileInfo,
      semaphore) -> Dict[str, List[str]]:
    """Bundle infra artifacts.

    Batch handler for infra artifact types.

    Args:
      chroot: The chroot to use.
      sysroot: The sysroot to use.
      outpath: Path to write bundled artifacts to.
      artifact_types: Artifact types to bundle.
      artifact_profile_info: profile information.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
        artifact bundling calls.

    Returns:
      A dict mapping artifact names to their absolute paths.
    """
    del chroot, sysroot, artifact_profile_info  # Unused.
    with semaphore:
      files_by_artifact = {}
      if ArtifactsByService.Infra.ArtifactType.BUILD_MANIFEST in artifact_types:
        with self.m.step.nest('create manifest.xml artifact'):
          outpath = outpath.join('manifest.xml')

          pinned_manifest_data = self.m.cros_source.pinned_manifest
          self.m.file.write_raw('write manifest.xml', outpath,
                                pinned_manifest_data)

          files_by_artifact['BUILD_MANIFEST'] = [str(outpath)]

      return files_by_artifact

  @staticmethod
  def _prepare_unknown(
      chroot: common_pb2.Chroot, sysroot: ArtifactsByService.Sysroot,
      artifact_types: List['BuilderConfig.Artifacts.ArtifactTypes'],
      input_artifacts: List[BuilderConfig.Artifacts.InputArtifactInfo],
      artifact_profile_info: common_pb2.ArtifactProfileInfo,
      test_data: str) -> artifacts.BuildSetupResponse:
    """Declare the build necessity UNKNOWN from this artifact's perspective.

    Use this prepare_for_build handler for any artifact type which has no
    prepare step.  It returns "UNKNOWN".

    Args:
      chroot: The chroot to use, or None if not yet created.
      sysroot: The sysroot to use, or None if not yet created.
      artifact_types: Artifact types to bundle.
      input_artifacts: Where to find input artifacts.
      artifact_profile_info: profile information.
      test_data: JSON data to use for build API calls.

    Returns:
      UNKNOWN.
    """
    del (chroot, sysroot, artifact_types, input_artifacts,
         artifact_profile_info, test_data)  # Unused.
    return artifacts.BuildSetupResponse.UNKNOWN

  def _prepare_toolchain(self, chroot, sysroot, artifact_types, input_artifacts,
                         artifact_profile_info, test_data):
    """Query the ToolchainService about the necessity of this build.

    Call ToolchainService.PrepareForBuild to prepare for the build.

    Args:
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      input_artifacts (list[InputArtifactInfo]): Where to find input artifacts.
      artifact_profile_info (ArtifactProfileInfo): profile information.
      test_data (str): JSON data to use for build API calls.

    Returns:
      (artifacts.BuildSetupResponse) whether build is necessary.
    """
    req = toolchain.PrepareForToolchainBuildRequest(
        chroot=chroot, sysroot=sysroot, artifact_types=artifact_types,
        input_artifacts=input_artifacts, profile_info=artifact_profile_info)
    resp = self.m.cros_build_api.ToolchainService.PrepareForBuild(
        req, infra_step=True, test_output_data=test_data)
    return resp.build_relevance

  def _bundle_toolchain(
      self, chroot: common_pb2.Chroot, sysroot: ArtifactsByService.Sysroot,
      path: config_types.Path,
      artifact_types: List['BuilderConfig.Artifacts.ArtifactTypes'],
      artifact_profile_info: common_pb2.ArtifactProfileInfo,
      semaphore) -> Dict[str, List[str]]:
    """Bundle toolchain artifacts.

    Batch handler for toolchain artifact types.

    Args:
      chroot: The chroot to use.
      sysroot: The sysroot to use.
      path: Path to write bundled artifacts to.
      artifact_types: Artifact types to bundle.
      artifact_profile_info: profile information.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
          artifact bundling calls.

    Returns:
      A dict mapping artifact names to their absolute paths.
    """
    with semaphore:
      req = toolchain.BundleToolchainRequest(sysroot=sysroot, chroot=chroot,
                                             output_dir=str(path),
                                             artifact_types=artifact_types,
                                             profile_info=artifact_profile_info)
      resp = self.m.cros_build_api.ToolchainService.BundleArtifacts(
          req, infra_step=True)
      ret = {}
      for art_info in resp.artifacts_info:
        artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(
            art_info.artifact_type)
        artifact_files = [art.path for art in art_info.artifacts]
        ret[artifact_name] = artifact_files
      return ret

  def _bundle_firmware(self, chroot: common_pb2.Chroot, path: config_types.Path,
                       artifact_info: ArtifactsByService.Firmware,
                       semaphore) -> Dict[str, List[str]]:
    """Bundle toolchain artifacts.

    Batch handler for toolchain artifact types.

    Args:
      chroot: The chroot to use.
      sysroot: The sysroot to use.
      path: Path to write bundled artifacts to.
      artifact_info: Firmware artifact info.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
          artifact bundling calls.

    Returns:
      A dict mapping artifact names to their absolute paths.
    """
    with semaphore:
      ret = {}
      if self.m.cros_build_api.has_endpoint(
          self.m.cros_build_api.FirmwareService, 'BundleFirmwareArtifacts'):
        req = firmware.BundleFirmwareArtifactsRequest(
            chroot=chroot, result_path=self._result_path(path),
            artifacts=artifact_info)
        req.bcs_version_info.version_string = str(self.m.cros_version.version)
        resp = self.m.cros_build_api.FirmwareService.BundleFirmwareArtifacts(
            req, infra_step=True)
        for art_info in resp.artifacts.artifacts:
          artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(
              art_info.artifact_type)
          artifact_files = [art.path for art in art_info.paths]
          ret[artifact_name] = artifact_files
      return ret

  def _bundle_artifacts(
      self, chroot: common_pb2.Chroot, sysroot: ArtifactsByService.Sysroot,
      artifacts_info: ArtifactsByService, outpath: config_types.Path,
      test_data: Optional[str] = None
  ) -> Tuple[Dict[str, List[str]], List[str]]:
    """Defer to the build API to bundle the given artifact.

    Args:
      chroot: chroot to use
      sysroot: sysroot to use
      artifacts_info: artifact information.
      outpath: Path to output artifact bundles.
      test_data: Some data for this step to return when running under
        simulation.  The string "@@DIR@@" is replaced with the output_dir
        path throughout.

    Returns:
      A tuple (files_by_artifact, failed_artifacts), where:
      * files_by_artifact is a dict mapping artifact names to a list of paths
        to those artifacts, relative to |outpath|.
      * failed_artifacts is a list of artifact types that failed to generate.
    """
    semaphore = self.m.futures.make_bounded_semaphore(
        self._max_concurrent_bundling_requests)
    futures = []

    futures.extend(
        self._bundle_artifacts_individually(chroot, sysroot, artifacts_info,
                                            outpath, semaphore))

    # Artifacts which are under the Get endpoint
    futures.append(
        self.m.futures.spawn(self._bundle_artifacts_by_service, chroot, sysroot,
                             artifacts_info, outpath, test_data, semaphore,
                             __name='bundle by service'))

    files_by_artifact = {}
    failed_artifacts = []
    for future in self.m.futures.iwait(futures):
      ex = future.exception()
      if ex:
        raise ex

      # The _bundle_artifacts_by_service function already returns the
      # artifacts in the correct form.
      if future.name == 'bundle by service':
        results, failures = future.result()
        files_by_artifact.update(results)
        failed_artifacts.extend(failures)
        continue

      for artifact, files in future.result().items():
        files_by_artifact[artifact] = [
            self.m.path.relpath(x, outpath) for x in files
        ]

    return files_by_artifact, failed_artifacts

  @staticmethod
  def _result_path(path, location=common_pb2.Path.OUTSIDE):
    """Construct a common_pb.ResultPath."""
    return common_pb2.ResultPath(
        path=common_pb2.Path(path=str(path), location=location))

  def _bundle_artifacts_by_service(
      self, chroot: common_pb2.Chroot, sysroot: ArtifactsByService.Sysroot,
      artifacts_info: ArtifactsByService, outpath: config_types.Path,
      test_data: Optional[str],
      semaphore) -> Tuple[Dict[str, List[str]], List[str]]:
    """Defer to the build API to bundle the given artifact.

    Args:
      chroot: chroot to use
      sysroot: sysroot to use
      artifacts_info: artifact information.
      outpath: Path to output artifact bundles.
      test_data: Some data for this step to return when running under
          simulation.  The string "@@DIR@@" is replaced with the output_dir
          path throughout.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
          artifact bundling calls.

    Returns:
      A tuple (files_by_artifact, failed_artifacts), where:
      * files_by_artifact is a dict mapping artifact names to a list of paths
        to those artifacts, relative to |outpath|.
      * failed_artifacts is a list of artifact types that failed to generate.
    """
    with self.m.step.nest('call artifacts service') as presentation:
      with semaphore:
        service = self.m.cros_build_api.ArtifactsService
        if not self.m.cros_build_api.has_endpoint(service, 'Get'):
          return {}, []

        req = artifacts.GetRequest(chroot=chroot, sysroot=sysroot,
                                   artifact_info=artifacts_info,
                                   result_path=self._result_path(outpath))

        if test_data:
          test_data = test_data.replace('@@DIR@@', str(outpath))
        resp = service.Get(req, infra_step=True, test_output_data=test_data)

        # Create files_by_artifact.
        files_by_artifact = {}
        failed_artifacts = []
        for service in json_format.MessageToDict(resp.artifacts).values():
          for paths in service.get('artifacts', []):
            if paths.get('failed', False):
              failed_artifacts.append(paths['artifactType'])
            if 'paths' in paths:
              files_by_artifact[paths['artifactType']] = [
                  self.m.path.relpath(f['path'], outpath)
                  for f in paths['paths']
              ]
        if failed_artifacts:
          presentation.step_text = 'Failed to generate: {}'.format(
              ', '.join(failed_artifacts))
          presentation.status = self.m.step.FAILURE
        return files_by_artifact, failed_artifacts

  def _bundle_artifacts_individually(self, chroot, sysroot, artifacts_info,
                                     outpath, semaphore):
    """Create Futures to call the per-artifact_type bundle functions.

    These are transitioning to ArtifactsService/BundleArtifacts (and
    _bundle_artifacts_by_service above), but will need to remain while any
    branches need that support.

    Args:
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use
      artifacts_info (ArtifactsByService): artifact information.
      outpath (Path): Path to output artifact bundles.
      semaphore (BoundedSemaphore): Semaphore to use to limit concurrency of
          artifact bundling calls.

    Returns:
      futures (list[Future]): A list of futures that call the per-artifact_type
          bundle functions.
    """
    futures = []
    # Sorting is done here only to give us consistency in the expected.json
    # for our tests.
    for _, service in sorted(artifacts_info.ListFields(),
                             key=lambda x: x[1].DESCRIPTOR.name):
      for art_info in getattr(service, 'output_artifacts', []):
        # The individual functions only exist for Toolchain, Legacy, Infra, and
        # Firmware. The others are only handled by ArtifactsService.Get().
        # TODO(b/231245311): Consider raising an exception if the artifact
        # belongs to a service which the Recipe does have logic to process.
        if (service.DESCRIPTOR.name == 'Firmware' and
            artifacts_info.firmware.output_artifacts):
          futures.append(
              self.m.futures.spawn(self._bundle_firmware, chroot, outpath,
                                   artifacts_info.firmware, semaphore))
        if service.DESCRIPTOR.name == 'Toolchain':
          futures.append(
              self.m.futures.spawn(self._bundle_toolchain, chroot, sysroot,
                                   outpath, art_info.artifact_types,
                                   artifacts_info.profile_info, semaphore))
        elif service.DESCRIPTOR.name == 'Legacy':
          futures.extend(
              self._bundle_legacy_artifacts(chroot, sysroot, outpath,
                                            art_info.artifact_types, semaphore))
        elif service.DESCRIPTOR.name == 'Infra':
          futures.append(
              self.m.futures.spawn(self._bundle_infra_artifacts, chroot,
                                   sysroot, outpath, art_info.artifact_types,
                                   artifacts_info.profile_info, semaphore))

    return futures

  def _artifacts_gs_path_dict(self, builder_name, target, kind):
    """Returns the dictionary tokens for expanding location templates.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. May be used as a descriptor in formatting paths.

    Returns:
      Dictionary of key:value pairs for building a gs_path.
    """
    # If there is a branch name in the builder_name, then we need to preserve
    # the builder name.
    version = self.m.cros_version.version
    ret = {
        'version':
            str(version),
        'legacy_version':
            version.legacy_version,
        # If this is a led launch, the ID will be in the format "led/user/id",
        # which has the side effect of breaking path parsing (which assumes the
        # last thing in this path starting with "/" will be version + build_id).
        # As such, remove all "/"s and replace with underscores.
        'build_id':
            str(
                self.m.buildbucket.build.id or
                self.m.led.run_id.replace('/', '_')),
        'target':
            target.name,
        'builder_name':
            builder_name.replace('_', '-'),
        'time':
            str(self._timestamp_micros),
    }
    if kind:
      ret['kind'] = BuilderConfig.Id.Type.Name(kind).lower().replace('_', '-')
      ret['label'] = ret['kind']
    ret['gs_path'] = '{builder}/{version}-{bid}'.format(
        builder=ret['builder_name'], version=ret['version'],
        bid=ret['build_id'])
    return ret

  def artifacts_gs_path(self, builder_name, target,
                        kind=BuilderConfig.Id.TYPE_UNSPECIFIED, template=None):
    """Returns the GS path for artifacts of the given kind for the given target.

    The resulting path will NOT include the GS bucket.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. May be used as a descriptor in formatting paths.
          Required if '{label}' or '{kind}' are present in |template|.
      template (str): The string to format, or None. If set to None, the
          default '{gs_path}' will be used.

    Returns:
      The formatted template.  Default: The GS path at which artifacts should
          be uploaded.
    """
    template = template or '{gs_path}'
    return template.format(
        **self._artifacts_gs_path_dict(builder_name, target, kind))

  def _publish_artifacts(self, builder_name, target, kind, artifacts_info,
                         upload_uri, files_by_artifact, name=None):
    """Publish the artifacts that were uploaded.

    Some artifacts need to also be published in a better-known place than the
    artifacts_gs_bucket.  (See chromite/scripts/pushimage.py for an example of
    how release builders publish some of the artifacts for release.)

    _publish_artifacts is called after upload_artifacts has copied everything to
    GS, so we publish the artifacts by copying them between GS buckets.

    When the publishing location for an artifact changes (such as toolchain
    artifacts moving from gs://chromeos-prebuilt to
    gs://chromeos-toolchain-artifact), there may be multiple publish_info
    entries for a single artifact_type.  This is to allow consumers of the
    artifact to transition seamlessly.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      target (BuildTarget): The build target with artifacts of interest.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This may affect where the artifacts are placed in
          Google Storage.
      artifacts_info (ArtifactsByService): Artifact information.
      upload_uri (string): gs path were the artifacts were uploaded.
      files_by_artifact (dict{name: list[string]}): artifact file dictionary.
      name (str): The step name.  Defaults to 'publish artifacts'.

    Returns:
      {name: link} of gs publishing directories used.
    """
    published = collections.defaultdict(list)
    links = {}
    # Get a list of all of the artifacts to publish:
    # [
    #   {artifact_types: [NAME, ...], gs_locations: [LOC, ...], acl_name=ACL},
    #   ...
    # ]
    to_publish = []
    for service in json_format.MessageToDict(artifacts_info).values():
      for out_info in service.get('outputArtifacts', []):
        if out_info.get('gsLocations') and out_info.get('artifactTypes'):
          to_publish.append(out_info)
    if not to_publish:
      return links

    # At this point, we know that we have at least one output artifact that has
    # both artifactTypes and gsLocations for publication.
    with self.m.step.nest(name or 'publish artifacts') as presentation:
      # location_dict['artifact_name'] will be set inside the loop.
      location_dict = self._artifacts_gs_path_dict(builder_name, target, kind)
      for info in to_publish:
        for publish_template in info['gsLocations']:
          for aname in info['artifactTypes']:
            files = files_by_artifact.get(aname, [])
            files = [x for x in files if x != '.']
            if files:
              location_dict['artifact_name'] = aname
              publish_loc = publish_template.format(**location_dict)
              link_name = 'gs publish dir: %s' % aname
              link_value = (
                  'https://console.cloud.google.com/storage/browser/%s' %
                  publish_loc)
              links[link_name] = link_value
              presentation.links[link_name] = link_value
              publish_uri = 'gs://' + publish_loc
              if not publish_uri.endswith('/'):
                publish_uri += '/'
              cmd = ['cp', '-r']
              if info.get('aclName'):
                cmd += ['-a', info.get('aclName')]
              cmd += ['%s/%s' % (upload_uri, path) for path in files]
              cmd.append(publish_uri)
              max_retries = 3
              for retries in range(max_retries):
                try:
                  self.m.gsutil(cmd, multithreaded=True,
                                timeout=self.test_api.gsutil_timeout_seconds)
                  break
                except recipe_api.StepFailure as ex:
                  if ex.had_timeout and retries < max_retries - 1:
                    continue
                  raise
              published[aname].append({
                  'gs_location': publish_loc,
                  'files': files
              })

    self.m.easy.set_properties_step(published=published,
                                    step_name='publish artifact GS paths')

    return links

  @staticmethod
  def has_output_artifacts(artifacts_info: ArtifactsByService) -> bool:
    """Return whether there are output artifacts.

    Args:
      artifacts: The artifacts config to check.

    Returns:
      Whether there are any output artifacts.
    """
    # Iterate over the components of artifacts_info, and return true if there
    # are any output_artifacts with artifact_types.
    for _, service in artifacts_info.ListFields():
      for art_info in getattr(service, 'output_artifacts', []):
        if art_info.artifact_types:
          return True
    return False

  @staticmethod
  def _filter_previously_uploaded_artifacts(
      artifacts_info: common_pb2.ArtifactsByService,
      previously_uploaded_artifacts: UploadedArtifacts
  ) -> common_pb2.ArtifactsByService:
    """Return a copy of artifacts_info, with all of previously_uploaded_artifacts removed.

    This function iterates each service in ArtifactsByService, and checks all
    artifact types in the output artifacts of the service; if the artifact type
    appears in previously_uploaded_artifacts, it will not be included in the
    returned copy of artifacts_info.

    Note that the EBUILD_LOGS is NOT filtered, as there are cases where this
    artifact changes after an initial upload (e.g. it can change between
    install packages and unit testing).

    Args:
      artifacts_info: ArtifactsByService to filter. Note that a copy will be
        made, this object will not be modified.
      previously_uploaded_artifacts: UploadedArtifacts from a previous call to
        upload_artifacts, these artifact types will be filtered.

    Returns:
      A copy of artifacts_info with the types in previously_uploaded_artifacts
        filtered.
    """
    filtered_artifacts_info = common_pb2.ArtifactsByService()
    filtered_artifacts_info.CopyFrom(artifacts_info)

    for _, service in filtered_artifacts_info.ListFields():
      # Each service is expected to have an 'output_artifacts' field, which
      # contains an 'artifact_types' field. However, we don't treat it as a
      # fatal error if a service doesn't contain these fields.
      if hasattr(service, 'output_artifacts'):
        # Create a list of output artifacts that still have at least one
        # artifact type after filtering.
        filtered_output_artifacts = []

        for art_info in service.output_artifacts:
          if hasattr(art_info, 'artifact_types'):
            # Create a list of artifact types that are not in
            # previously_uploaded_artifacts.
            filtered_artifact_types = []
            for art_type in art_info.artifact_types:
              type_name = BuilderConfig.Artifacts.ArtifactTypes.Name(art_type)
              # EBUILD_LOGS type is always included.
              if (type_name
                  not in previously_uploaded_artifacts.files_by_artifact or
                  art_type
                  == BuilderConfig.Artifacts.ArtifactTypes.EBUILD_LOGS):
                filtered_artifact_types.append(art_type)

            # Set artifact_types to the new filtered list.
            art_info.artifact_types[:] = filtered_artifact_types

            # Only include the ArtifactInfo in the output if it has at least
            # one artifact type.
            if art_info.artifact_types:
              filtered_output_artifacts.append(art_info)

        # Overwrite the service's output_artifacts field with the filtered list.
        # Note that directly setting `service.output_artifacts[:] = ...` is not
        # supported on repeated message fields.
        del service.output_artifacts[:]
        service.output_artifacts.extend(filtered_output_artifacts)

    return filtered_artifacts_info

  def upload_artifacts(
      self, builder_name, kind, gs_bucket, *, artifacts_info=None, chroot=None,
      sysroot=None, name='upload artifacts', test_data=None,
      private_bundle_func=None, report_to_spike=False,
      attestation_eligible=False, upload_coverage=True,
      previously_uploaded_artifacts=None,
      ignore_breakpad_symbol_generation_errors=False
  ) -> Tuple[Optional[UploadedArtifacts], Optional[config_types.Path]]:
    """Bundle and upload the given artifacts for the given build target.

    This function sets the "artifacts" output property to include the
    GS bucket, the path within that bucket, and a dict mapping artifact
    to a list of artifact paths (relative to the GS path) for each artifact
    type that was uploaded.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
          Google Storage.
      gs_bucket (str): Google storage bucket to upload artifacts to.
      artifacts_info (ArtifactsByService): Information about artifacts.
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use (this contains the build target.)
      name (str): The step name. Defaults to 'upload artifacts'.
      test_data (str): Some data for this step to return when running under
          simulation.  The string "@@DIR@@" is replaced with the output_dir
          path throughout.
      private_bundle_func (func): If a private bundling method is needed (such
          as when there is no Build API on the branch), this will be called
          instead of the internal bundling method.
      report_to_spike(bool): If True, will call bcid_reporter to report artifact
          information and trigger Spike to upload the provenance as
          [artifact-name].attestation if attestation_eligible is true.
      attestation_eligible(bool): Will call bcid_reporter to report artifact information if
          report_to_spike is also true. This is set in BuilderConfig.Artifacts.AttestationEligible.
      upload_coverage(bool): If True, we will run the upload coverage step and
           store coverage information. This should be set of False when we dont
           run unit tests and hence have no coverage information to store.
      previously_uploaded_artifacts(UploadedArtifacts): If set, the
        UploadedArtifacts from a previous call to upload_artifacts; these artifact
        types will not be re-uploaded. This used to avoid re-bundling artifacts
        if upload_artifacts is called multiple times.
      ignore_breakpad_symbol_generation_errors: If True, the
        BREAKPAD_DEBUG_SYMBOLS step will ignore any errors during symbol
        generation.

    Returns:
      (UploadedArtifacts) information about uploaded artifacts.
      (Path) path to local dir where artifacts are staged.
    """
    uploaded_artifacts = None

    if previously_uploaded_artifacts:
      artifacts_info = self._filter_previously_uploaded_artifacts(
          artifacts_info, previously_uploaded_artifacts)

    if ignore_breakpad_symbol_generation_errors and artifacts_info and artifacts_info.HasField(
        'sysroot'):
      artifacts_info.sysroot.ignore_breakpad_symbol_generation_errors = True

    with self.m.cros_build_api.parallel_operations(), self.m.step.nest(
        name) as presentation:
      outpath = self.m.path.mkdtemp(prefix='artifacts')
      func = private_bundle_func or self._bundle_artifacts
      try:
        files_by_artifact = {}
        failed_artifacts = []
        result = func(chroot, sysroot, artifacts_info, outpath, test_data)
        files_by_artifact = result
        # _bundle_artifacts is the only function that returns failed artifacts.
        if func.__name__ == '_bundle_artifacts':
          files_by_artifact, failed_artifacts = result
      except Exception as e:
        self.m.disk_usage.track(step_name='track disk usage', depth=2,
                                d=self.m.path['cache'])
        raise e

      if not files_by_artifact:
        if failed_artifacts:
          raise StepFailure('Failed to generate: {}'.format(
              ', '.join(failed_artifacts)))
        presentation.step_text = 'No artifacts found.'
        return uploaded_artifacts, None

      # Upload all of the artifacts to the archive bucket/path.
      gs_path = self.artifacts_gs_path(builder_name, sysroot.build_target, kind,
                                       template=self._gs_upload_path)
      presentation.links['gs upload dir'] = (
          'https://console.cloud.google.com/storage/browser/%s/%s' %
          (gs_bucket, gs_path))
      upload_uri = 'gs://%s/%s' % (gs_bucket, gs_path)
      self.m.easy.set_properties_step('set artifact_link property',
                                      artifact_link=upload_uri)

      if report_to_spike and attestation_eligible:
        image_archives = files_by_artifact.get('IMAGE_ARCHIVES', [])

        artifact_basenames = []
        if image_archives:
          artifact_basenames.extend(
              [self.m.path.basename(i) for i in image_archives])
        else:
          presentation.logs[
              'report_to_spike'] = 'IMAGE_ARCHIVES not in files_by_artifact'

        # The artifact to generate provenance for.
        # This list will be expanded as more artifacts are enrolled in
        # provenance generation.
        artifacts_to_report = [BASE_IMAGE_TAR, RECOVERY_IMAGE_TAR]

        paths_to_hash = {
            self.m.path.join(outpath, i): i
            for i in artifact_basenames
            if i in artifacts_to_report
        }

        # Also generate provenance for all DLCs placed locally by BAPI.
        # TODO(b/277931195): Remove ignore exceptions when stable.
        with self.m.failures.ignore_exceptions():
          self.m.dlc_utils.artifacts_local_path = str(outpath)
          dlc_local_paths = self.m.dlc_utils.get_dlcs_in_path(
              outpath, use_local_path=True)
          for dlc in dlc_local_paths:
            paths_to_hash[dlc] = self.m.path.relpath(dlc, outpath)

          with self.m.step.nest('generate provenance'):
            for abspath, basepath in paths_to_hash.items():
              file_hash = self.m.file.file_hash(abspath, test_data='deadbeef')
              self.m.bcid_reporter.report_gcs(
                  file_hash, '{uri}/{item}'.format(uri=upload_uri,
                                                   item=basepath))

      for retries in range(3):
        try:
          self.m.gsutil(['rsync', '-r', outpath, upload_uri],
                        parallel_upload=True, multithreaded=True,
                        timeout=self.test_api.gsutil_timeout_seconds)
          break
        except recipe_api.StepFailure as ex:
          if ex.had_timeout and retries < 2:
            continue
          raise

      uploaded_artifacts = UploadedArtifacts(gs_bucket, gs_path,
                                             files_by_artifact)

      # If there were previously uploaded artifacts, we want to include them in
      # the artifacts output property.
      if previously_uploaded_artifacts:
        self.merge_artifacts_properties(
            [uploaded_artifacts, previously_uploaded_artifacts])
      else:
        self._set_artifacts_property(uploaded_artifacts)

      # We upload artifacts whether the build passed or failed (see
      # crbug/1086630).

      # TODO(b/193131170): Switch to using updated ArtifactInfo fields.
      for fname in files_by_artifact.get('FIRMWARE_LCOV', []):
        with self.m.failures.ignore_exceptions():
          self.m.code_coverage.upload_firmware_lcov(outpath.join(fname))

      for fname in files_by_artifact.get('CODE_COVERAGE_E2E', []):
        self.m.code_coverage.update_e2e_metadata(gs_bucket, gs_path)

      if upload_coverage:
        cov_files = {}
        cov_files['LLVM'] = files_by_artifact.get('CODE_COVERAGE_LLVM_JSON', [])
        cov_files['LLVM'].extend(
            files_by_artifact.get('CODE_COVERAGE_RUST_LLVM_JSON', []))
        cov_files['GO_COV'] = files_by_artifact.get('CODE_COVERAGE_GOLANG', [])
        for coverage_type, fnames in cov_files.items():
          for fname in fnames:
            self.m.code_coverage.upload_code_coverage(
                outpath.join(fname), coverage_type, gs_bucket, gs_path)

      # Builders that publish artifacts should not recycyle dry-run builds,
      # since we treat them differently here.
      if self.m.cq.active and self.m.cq.run_mode == self.m.cq.DRY_RUN:
        if failed_artifacts:
          raise StepFailure(
              f'Failed to generate: {", ".join(failed_artifacts)}')
        with self.m.step.nest('skip publish artifacts') as presentation:
          presentation.step_text = 'Not publishing artifacts in dry run'
          return uploaded_artifacts, outpath

      # Builders can specify not to publish artifacts (e.g. tryjob artifacts).
      if self.skip_publish:
        with self.m.step.nest('skip publish artifacts') as presentation:
          presentation.step_text = 'skip_publish property set'
      else:
        # Now publish any artifacts that have publishing information.  This is
        # done here (rather than adding api.cros_artifacts.publish_artifacts)
        # because we know that we just uploaded all of the artifacts to GS
        # successfully, and can therefore copy them GS->GS, and avoid
        # re-uploading. Publishing is intentionally nested under upload
        # artifacts.
        links = self._publish_artifacts(builder_name, sysroot.build_target,
                                        kind, artifacts_info, upload_uri,
                                        files_by_artifact)
        for k, v in sorted(links.items()):
          presentation.links[k] = v
    if failed_artifacts:
      raise StepFailure('Failed to generate: {}'.format(
          ', '.join(failed_artifacts)))
    return uploaded_artifacts, outpath

  def upload_metadata(self, name, builder_name, target, gs_bucket, filename,
                      message, template=None):
    """Materialize a protobuffer message as a jsonpb artifact in GCS.

    Convert the message to a jsonpb file and upload it to the appropriate
    location in GCS with the other build artifacts.

    Args:
      name (str): Human readable metadata name for step name.
      builder_name (str): The builder name, e.g. octopus-cq.
      target (str|): Build target, eg: octopus-kernelnext.
      gs_bucket (str): Google storage bucket to upload artifacts to.
      filename (str): Filename for the metadata.
      message (Message): Protobuffer message to serialize and upload.
      template (str): The string to format for artifacts_gs_path, or None. If
          set to None, the default artifacts_gs_path template will be used.

    Returns:
      GS path inside bucket to uploaded file
    """

    with self.m.step.nest('upload {} metadata'.format(name)):
      # Wrap target up into a BuildTarget proto if needed
      if isinstance(target, str):
        target = common_pb2.BuildTarget(name=target)

      # Add a .jsonpb extension to the filename if we don't have one.
      path, ext = self.m.path.splitext(filename)
      if not ext:
        ext = '.jsonpb'
      filename = ''.join([path, ext])

      gs_path = self.m.path.join(
          self.artifacts_gs_path(builder_name, target, template=template),
          self.m.metadata.METADATA_GSDIR,
          filename,
      )

      full_path = self.m.path.mkdtemp().join(filename)
      self.m.file.write_proto('writing metadata', full_path, message, 'JSONPB')

      self.m.gsutil.upload(full_path, gs_bucket, gs_path,
                           timeout=self.test_api.gsutil_timeout_seconds)

      return gs_path

  def merge_artifacts_properties(self, properties: List[UploadedArtifacts]):
    """Combine uploaded artifacts to produce a final value.

    Args:
      properties (list[UploadedArtifacts]): the values to merge.
    """
    assert properties
    ret = properties[0]
    for prop in properties[1:]:
      ret = ret.union(prop)
    self._set_artifacts_property(ret)
    return ret

  def _set_artifacts_property(self, uploaded_artifacts):
    """Set output property.

    Args:
      uploaded_artifacts (UploadedArtifacts): The uploaded artifacts
    """
    these_artifacts = uploaded_artifacts._asdict()
    self.m.easy.set_properties_step(artifacts=these_artifacts,
                                    step_name='output artifact GS paths')

  def download_artifact(self, build_payload, artifact, name=None):
    """Download the given artfiact from the given build payload.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      artifact (ArtifactType): The artifact to download.
      name (string): step name.  Defaults to 'download |artifact_name|'.

    Returns:
      list[Path]: Paths to the files downloaded from GS.

    Raises:
      ValueError: If the artifact is not found in the build payload.
    """
    artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
    gs_bucket = build_payload.artifacts_gs_bucket
    gs_path = build_payload.artifacts_gs_path
    gs_file_names_by_artifact = json_format.MessageToDict(
        build_payload.files_by_artifact)
    gs_file_names = gs_file_names_by_artifact.get(artifact_name)
    if gs_file_names is None:
      raise ValueError('artifact %s not found in payload' % artifact_name)

    with self.m.step.nest(name or 'download %s' % artifact_name):
      download_root = self.m.path.mkdtemp(prefix='%s-' % artifact_name)
      download_paths = []
      for gs_file_name in gs_file_names:
        download_path = download_root.join(gs_file_name)
        self.m.gsutil.download(gs_bucket,
                               self.m.path.join(gs_path,
                                                gs_file_name), download_path)
        download_paths.append(download_path)
      return download_paths

  def download_artifacts(self, build_payload, artifact_types, name=None):
    """Download the given artifacts from the given build payload.

    Args:
      build_payload (BuildPayload): Describes where build artifacts are on GS.
      artifact_types (list[ArtifactTypes]): The artifact types to download.
      name (str): The step name. Defaults to 'download artifacts'.

    Returns:
      dict: Maps ArtifactType to list[Path] representing downloaded files.

    Raises:
      ValueError: If any artifact is not found in the build payload.
    """
    with self.m.step.nest(name or 'download artifacts'):
      return {
          artifact: self.download_artifact(build_payload, artifact)
          for artifact in artifact_types
      }

  def prepare_for_build(self, chroot, sysroot, artifacts_info,
                        forced_build_relevance=False, test_data=None,
                        name=None):
    """Prepare the build for the given artifacts.

    This function calls the Build API to have it prepare to build artifacts of
    the given types.

    Args:
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      artifacts_info (ArtifactsByService): artifact information.
      forced_build_relevance (bool): Whether the builder will be ignoring the
          response.
      test_data (str): JSON data to use for ArtifactsService call.
      name (str): The step name. Defaults to 'prepare artifacts'.

    Returns:
      PrepareForToolchainBuildResponse.BuildRelevance indicating that the build
      is NEEDED (regardless of the cq relevance check), UNKNOWN (pointless
      build check applies), or POINTLESS (just exit now.)
    """
    with self.m.step.nest(name or 'prepare artifacts') as presentation:
      ret = self._prepare_for_build(chroot, sysroot, artifacts_info,
                                    forced_build_relevance, test_data)

      self.m.easy.set_properties_step(
          artifact_prep=json_format.MessageToDict(
              artifacts.BuildSetupResponse(build_relevance=ret)),
          step_name='set artifact_prep')
      if ret == artifacts.BuildSetupResponse.NEEDED:
        presentation.step_text = 'Build is NEEDED'
      elif ret == artifacts.BuildSetupResponse.UNKNOWN:
        presentation.step_text = 'Build need is UNKNOWN'
      else:
        presentation.step_text = 'Build is POINTLESS'
    return ret

  def _prepare_for_build(self, chroot, sysroot, artifacts_info,
                         forced_build_relevance, test_data):
    """Prepare the build for the given artifacts, using Build API version 1.0.0.

    This function calls the Build API to have it prepare to build artifacts of
    the given types.

    Args:
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      artifacts_info (ArtifactsByService): artifact information.
      forced_build_relevance (bool): Whether the builder will be ignoring the
          response.
      test_data (str): JSON data to use for build API calls.

    Returns:
      PrepareForToolchainBuildResponse.BuildRelevance indicating that the build
      is NEEDED (regardless of the cq relevance check), UNKNOWN (pointless
      build check applies), or POINTLESS (just exit now.)
    """
    # By default, artifacts will get 'UNKNOWN'.
    # EBUILD_LOGS are not relevant.
    _IGNORE_ARTIFACT_TYPES = [BuilderConfig.Artifacts.EBUILD_LOGS]
    POINTLESS = artifacts.BuildSetupResponse.POINTLESS
    NEEDED = artifacts.BuildSetupResponse.NEEDED
    UNKNOWN = artifacts.BuildSetupResponse.UNKNOWN

    if (self._test_data.enabled and
        self._test_data.get('set_prepare_pointless', False)):
      return POINTLESS

    funcs = collections.defaultdict(list)
    input_artifacts = []
    for _, service in artifacts_info.ListFields():
      for art_info in getattr(service, 'output_artifacts', []):
        if service.DESCRIPTOR.name == 'Toolchain':
          funcs[self._prepare_toolchain].extend(art_info.artifact_types)
        else:
          # If it's not Toolchain, then it's legacy.  1.0.0 only supports those
          # two services having artifacts.
          for art in art_info.artifact_types:
            if art not in _IGNORE_ARTIFACT_TYPES:
              funcs[self._prepare_unknown].append(art)

      # input_artifacts is the list of input_artifacts, rewritten into the
      # correct message type.
      for in_art in getattr(service, 'input_artifacts', []):
        for atype in in_art.artifact_types:
          # TODO(b/275625143): Remove in M-115+.
          # Don't run the 5.15 kernel amd64 afdo builder if the chromeos
          # version is below 113.
          if (self.m.cros_version.version.milestone < 113 and
              atype == BuilderConfig.Artifacts.VERIFIED_KERNEL_CWP_AFDO_FILE and
              any('amd64/5.15' in gs_location
                  for gs_location in in_art.gs_locations)):
            return POINTLESS
          input_artifacts.append(
              BuilderConfig.Artifacts.InputArtifactInfo(
                  input_artifact_type=atype,
                  input_artifact_gs_locations=in_art.gs_locations))

    res = {}
    # TODO(crbug/1034529): Eventually ArtifactsService/BuildSetup will handle
    # everything for us.  To ease migration, call both and merge the results.
    ArtifactsService = self.m.cros_build_api.ArtifactsService
    if self.m.cros_build_api.has_endpoint(ArtifactsService, 'BuildSetup'):
      req = artifacts.BuildSetupRequest(
          chroot=chroot, sysroot=sysroot, artifact_info=artifacts_info,
          forced_build_relevance=forced_build_relevance)
      res[ArtifactsService.BuildSetup] = ArtifactsService.BuildSetup(
          req, infra_step=True, test_output_data=test_data).build_relevance
    elif not funcs:
      return UNKNOWN

    # Sorting is done here only to give us consistency in the expected.json
    # for our tests.
    with self.m.step.nest('call prepare funcs') as pres:
      for func, types in sorted(funcs.items(), key=lambda x: x[0].__name__):
        res[func] = func(chroot, sysroot, types, input_artifacts,
                         artifacts_info.profile_info, test_data=test_data)
        pres.logs[func.__name__] = '%s => %s' % ([
            BuilderConfig.Artifacts.ArtifactTypes.Name(x) for x in types
        ], artifacts.BuildSetupResponse.BuildRelevance.Name(res[func]))

    result = POINTLESS
    if NEEDED in res.values():
      # NEEDED has the highest priority.
      result = NEEDED
    elif res.get(self._prepare_toolchain, UNKNOWN) == POINTLESS:
      # Prefer returning a pointless toolchain result to returning unknown results.
      result = POINTLESS
    elif UNKNOWN in res.values():
      result = UNKNOWN
    # We come here if there are:
    # - no NEEDED and UNKNOWN results and
    # - there are no toolchain artifacts.

    return result

  def push_image(self, chroot, gs_image_dir, sysroot, dryrun=False,
                 profile=None, sign_types=None, dest_bucket=None,
                 channels=None):
    """Call the PushImage build API endpoint.

      Args:
        chroot (Chroot): The chroot to use, or None if not yet created.
        gs_image_dir (string): The source directory (a gs path) to push from.
        sysroot (Sysroot): The sysroot (build target) to use.
        profile (Profile): The profile to use, or None.
        sign_types (list(ImageType)): The sign types to use, or None.
        dest_bucket (string): The destination bucket to use, or None.
        channels (list(Channel)): The channels to use, or empty list.

        For more context on this parameters, see chromite/scripts/pushimage.py.

      Returns:
        PushImageResponse
      """
    request = PushImageRequest(
        chroot=chroot,
        gs_image_dir=gs_image_dir,
        sysroot=sysroot,
        dryrun=dryrun,
        profile=profile,
        sign_types=sign_types,
        dest_bucket=dest_bucket,
        channels=channels,
        is_staging=self.m.cros_infra_config.is_staging,
    )
    return self.m.cros_build_api.ImageService.PushImage(request)

  def publish_latest_files(self, gs_bucket, gs_path):
    """Write LATEST-... files to GS.

    Writes version information to the LATEST-{version} and LATEST-{branch} files
    in the specified GS dir. Will only write LATEST-{branch} if the version is
    more recent than the existing contents.

    Args:
      gs_bucket (str): GS bucket to write to.
      gs_path (str): GS path to write to (relative to the bucket),
        e.g. eve-release.
    """
    with self.m.step.nest('write LATEST files'):
      # e.g. R100-12345.0.0.
      version = self.m.cros_version.version

      tmp_dir = self.m.path.mkdtemp(prefix='LATEST')
      tmp_file = tmp_dir.join('LATEST')
      contents = str(version)
      self.m.file.write_raw('write "{}" to tmp LATEST file'.format(contents),
                            tmp_file, contents)

      partial_cmd = ['cp', tmp_file]

      gs_template = 'gs://{gs_bucket}/{gs_path}/'
      gs_base_path = gs_template.format(gs_bucket=gs_bucket, gs_path=gs_path)

      # Write version LATEST file, e.g. LATEST-12345.0.0.
      version_file = 'LATEST-%s' % version.platform_version
      with self.m.step.nest('write {}'.format(version_file)):
        version_file_path = gs_base_path + version_file
        self.m.gsutil(cmd=partial_cmd + [version_file_path],
                      name='write %s' % version_file_path,
                      use_retry_wrapper=True)

      config = self.m.cros_infra_config.config
      if not config:
        raise StepFailure(
            'could not find builder config, needed to determine branch')
      branch = config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]

      # Write branch LATEST file, e.g. LATEST-main.
      branch = 'main' if self.m.cros_source.is_tot else branch
      branch_file = 'LATEST-{}'.format(branch)
      with self.m.step.nest('write {}'.format(branch_file)) as presentation:
        branch_file_path = gs_base_path + branch_file

        # Read branch LATEST file to see if the version listed is more recent.
        ret = self.m.gsutil.cat(branch_file_path,
                                stdout=self.m.raw_io.output_text(),
                                ok_ret=(0, 1), use_retry_wrapper=True)

        if ret.stdout:
          current_latest_version = self.m.cros_version.Version.from_string(
              ret.stdout.strip())
          if current_latest_version > version:
            presentation.step_text = '{} has more recent version, skipping'.format(
                branch_file_path)
            return
        self.m.gsutil(cmd=partial_cmd + [branch_file_path],
                      name='write %s' % branch_file_path,
                      use_retry_wrapper=True)
