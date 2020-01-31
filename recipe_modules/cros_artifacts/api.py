# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

import collections
import os

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromite.api import artifacts
from PB.chromite.api import toolchain
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import PrepareForBuildResponse

# Legacy artifacts and their handling.
ARTIFACTS_SERVICE = 'chromite.api.ArtifactsService'

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
    BuilderConfig.Artifacts.CPE_REPORT: 'ExportCpeReport',
    BuilderConfig.Artifacts.IMAGE_ARCHIVES: 'BundleImageArchives',
}


class CrosArtifactsApi(recipe_api.RecipeApi):
  """A module for bundling and uploading build artifacts."""

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
        'with the current build config.' % (
            BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)))
    return getattr(self.m.cros_build_api.ArtifactsService,
                   _LEGACY_ENDPOINTS_BY_ARTIFACT[artifact])

  def _bundle_legacy_artifacts(self, chroot, sysroot, path, artifact_types):
    """Bundle legacy artifacts.

    Batch handler for legacy artifact types.

    Args:
      chroot (Chroot): The chroot to use.
      sysroot (Sysroot): The sysroot to use.
      path (Path): Path to write bundled artifacts to.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.

    Returns:
      dict(artifact_name: list(artifact paths)).  Paths are relative to |path|.
    """
    files_by_artifact = {}
    for artifact in artifact_types:
      name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
      with self.m.step.nest('bundle %s for upload' % name):
        endpoint = self._get_legacy_endpoint(artifact)
        request = artifacts.BundleRequest(
            chroot=chroot, sysroot=sysroot, build_target=sysroot.build_target,
            output_dir=str(path))
        response = endpoint(request, infra_step=True)

        files_by_artifact[name] = [
            os.path.relpath(art.path, str(path)) for art in response.artifacts
        ]
    return files_by_artifact

  def _prepare_unknown(
      self, _chroot, _sysroot, _artifact_types, _input_artifacts):
    """Prepare for Build.

    Use this prepare_for_build handler for any artifact type which has no
    prepare step.  It simply returns "UNKNOWN".

    Args:
      _chroot (Chroot): The chroot to use, or None if not yet created.
      _sysroot (Sysroot): The sysroot to use, or None if not yet created.
      _artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      _input_artifacts (list[InputArtifactInfo]): Where to find input artifacts.

    Returns:
      (PrepareForBuildResponse.build_relevance) build relevance.
    """
    return PrepareForBuildResponse.UNKNOWN

  def _prepare_toolchain(
      self, chroot, sysroot, artifact_types, input_artifacts):
    """Prepare for Build.

    Call ToolchainService.PrepareForBuild to prepare for the build.

    Args:
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      input_artifacts (list[InputArtifactInfo]): Where to find input artifacts.

    Returns:
      (PrepareForBuildResponse) whether build is necessary.
    """
    req = toolchain.PrepareForToolchainBuildRequest(
        chroot=chroot, sysroot=sysroot, artifact_types=artifact_types,
        input_artifacts=input_artifacts)
    resp = self.m.cros_build_api.ToolchainService.PrepareForBuild(
        req, infra_step=True)
    result = resp.build_relevance

    if result == toolchain.PrepareForToolchainBuildResponse.NEEDED:
      return PrepareForBuildResponse.NEEDED
    elif result == toolchain.PrepareForToolchainBuildResponse.UNKNOWN:
      return PrepareForBuildResponse.UNKNOWN
    return PrepareForBuildResponse.POINTLESS

  def _bundle_toolchain(self, chroot, sysroot, path, artifact_types):
    """Bundle toolchain artifacts.

    Batch handler for toolchain artifact types.

    Args:
      chroot (Chroot): The chroot to use.
      sysroot (Sysroot): The sysroot to use.
      path (Path): Path to write bundled artifacts to.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.

    Returns:
      dict(artifact_name: list(artifact paths)).  Paths are relative to |path|.
    """
    req = toolchain.BundleToolchainRequest(
        sysroot=sysroot, chroot=chroot, output_dir=str(path),
        artifact_types=artifact_types)
    resp = self.m.cros_build_api.ToolchainService.BundleArtifacts(
        req, infra_step=True)
    ret = {}
    for art_info in resp.artifacts_info:
      artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(
          art_info.artifact_type)
      artifact_files = [
          os.path.relpath(art.path, str(path)) for art in art_info.artifacts
      ]
      ret[artifact_name] = artifact_files
    return ret

  def _partition_artifacts(self, artifact_types, func_dict):
    """Partition the artifacts by handler.

    Args:
      artifact_types: (list[ArtifactTypes]): The artifacts to partition.
      func_dict: (dict(artifact_type: function)) Function dictionary.

    Returns:
      dict(function: list[ArtifactTypes]): each function should be called with
      the given list of artifact types.
    """
    ret = collections.defaultdict(list)
    for art in artifact_types:
      # Raises KeyError if there is an artifact not found in func_dict.
      ret[func_dict[art]].append(art)
    return ret

  def _bundle_artifacts(self, artifact_types, path, sysroot, chroot):
    """Defer to the build API to bundle the given artifact.

    Args:
      artifact_types (list[ArtifactTypes]): The artifacts to bundle.
      path (Path): Path to output artifact bundles.
      sysroot (Sysroot): sysroot to use
      chroot (Chroot): chroot to use

    Returns:
      dict(str: list[str]): Artifact name, list of artifact file paths
          relative to |path|.
    """
    _BUNDLE_FUNCS = {
        BuilderConfig.Artifacts.IMAGE_ZIP: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD:
            self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.AUTOTEST_FILES: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.TAST_FILES: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.PINNED_GUEST_IMAGES:
            self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.FIRMWARE: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.EBUILD_LOGS: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.CHROMEOS_CONFIG: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.CPE_REPORT: self._bundle_legacy_artifacts,
        BuilderConfig.Artifacts.UNVERIFIED_ORDERING_FILE:
            self._bundle_toolchain,
        BuilderConfig.Artifacts.VERIFIED_ORDERING_FILE: self._bundle_toolchain,
        BuilderConfig.Artifacts.CHROME_CLANG_WARNINGS_FILE:
            self._bundle_toolchain,
        BuilderConfig.Artifacts.UNVERIFIED_LLVM_PGO_FILE:
            self._bundle_toolchain,
        BuilderConfig.Artifacts.UNVERIFIED_CHROME_AFDO_FILE:
            self._bundle_toolchain,
        BuilderConfig.Artifacts.VERIFIED_CHROME_AFDO_FILE:
            self._bundle_toolchain,
        BuilderConfig.Artifacts.VERIFIED_KERNEL_AFDO_FILE:
            self._bundle_toolchain,
    }

    files_by_artifact = {}
    funcs_to_call = self._partition_artifacts(artifact_types, _BUNDLE_FUNCS)
    for func, types in funcs_to_call.items():
      files_by_artifact.update(func(chroot, sysroot, path, types))
    return files_by_artifact

  def _artifacts_gs_path_dict(self, target, kind):
    """Returns the dictionary tokens for expanding location templates.

    Args:
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. Used as a descriptor in the GS path.

    Returns:
      Dictionary of key:value pairs for building a gs_path.
    """
    ret = {
        'label': BuilderConfig.Id.Type.Name(kind).lower().replace('_', '-'),
        'version': self.m.cros_version.read_workspace_version(),
        'build_id': self.m.buildbucket.build.id,
        'target': target.name,
    }
    ret['gs_path'] = '%s-%s/%s-%d' % (
        ret['target'], ret['label'], ret['version'], ret['build_id'])
    return ret

  def artifacts_gs_path(self, target, kind):
    """Returns the GS path for artifacts of the given kind for the given target.

    The resulting path will NOT include the GS bucket.

    Args:
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. Used as a descriptor in the GS path.

    Returns:
      The GS path at which artifacts should be uploaded.
    """
    return self._artifacts_gs_path_dict(target, kind)['gs_path']

  def _publish_artifacts(self, target, kind, publish_info, upload_uri,
                         files_by_artifact, name=None):
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
      target (BuildTarget): The build target with artifacts of interest.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
          Google Storage.
      publish_info (list[PublishInfo]): List of publishing information.
      upload_uri (string): gs path were the artifacts were uploaded.
      files_by_artifact (dict{name: list[string]}): artifact file dictionary.
      name (str): The step name.  Defaults to 'publish artifacts'.

    Returns:
      {name: link} of gs publishing directories used.
    """
    published = collections.defaultdict(list)
    links = {}
    with self.m.step.nest(name or 'publish artifacts') as step:
      for info in publish_info:
        publish_template = info.publish_gs_location
        location_dict = self._artifacts_gs_path_dict(target, kind)
        for artifact in info.publish_types:
          artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
          files = files_by_artifact.get(artifact_name, [])
          if files:
            location_dict['artifact_name'] = artifact_name
            publish_loc = publish_template.format(location_dict)
            link_name = 'gs publish dir: %s' % artifact_name
            link_value = (
                'https://console.cloud.google.com/storage/browser/%s' %
                publish_loc)
            links[link_name] = link_value
            step.presentation.links[link_name] = link_value
            publish_uri = 'gs://' + publish_loc
            if not publish_uri.endswith('/'):
              publish_uri += '/'
            cmd = ['cp'] + ['%s/%s' % (upload_uri, path) for path in files]
            cmd.append(publish_uri)
            for retries in range(3):
              try:
                self.m.gsutil(cmd, multithreaded=True,
                              timeout=self.test_api.gsutil_timeout_seconds)
                break
              except recipe_api.StepFailure as ex:
                if ex.had_timeout and retries < 2:
                  continue
                else:
                  raise
            published[artifact_name].append({
                'gs_location': publish_loc, 'files': files})

      self.m.easy.set_property_step(
          'published', published, step_name='publish artifact GS paths')

      return links

  def upload_artifacts(self, target, kind, gs_bucket, artifact_types,
                       chroot=None, sysroot=None,
                       publish_info=None, name=None):
    """Bundle and upload the given artifacts for the given build target.

    This function sets the "artifacts" output property to include the
    GS bucket, the path within that bucket, and a dict mapping artifact
    to a list of artifact paths (relative to the GS path) for each artifact
    type that was uploaded.

    Args:
      target (BuildTarget): The build target with artifacts of interest.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
          Google Storage.
      gs_bucket (str): Google storage bucket to upload artifacts to.
      artifact_types (list[ArtifactTypes]): List of artifacts
          to upload. See build config for options.
      sysroot (Sysroot): sysroot to use
      chroot (Chroot): chroot to use
      publish_info (list[PublishInfo]): List of publishing information.
      name (str): The step name. Defaults to 'upload artifacts'.
    """
    with self.m.step.nest(name or 'upload artifacts') as step:
      staging_root = self.m.path.mkdtemp(prefix='artifacts')

      files_by_artifact = self._bundle_artifacts(
          artifact_types, staging_root, sysroot, chroot)

      gs_path = self.artifacts_gs_path(target, kind)
      step.presentation.links['gs upload dir'] = (
          'https://console.cloud.google.com/storage/browser/%s/%s' %
          (gs_bucket, gs_path))
      upload_uri = 'gs://%s/%s' % (gs_bucket, gs_path)
      for retries in range(3):
        try:
          self.m.gsutil(['rsync', staging_root, upload_uri],
                        parallel_upload=True, multithreaded=True,
                        timeout=self.test_api.gsutil_timeout_seconds)
          break
        except recipe_api.StepFailure as ex:
          if ex.had_timeout and retries < 2:
            continue
          else:
            raise

      self.m.easy.set_property_step(
          'artifacts', {
              'gs_bucket': gs_bucket,
              'gs_path': gs_path,
              'files_by_artifact': files_by_artifact,
          }, step_name='output artifact GS paths')

      # Now publish any artifacts that have publishing information.  This is
      # done here (rather than adding api.cros_artifacts.publish_artifacts)
      # because we know that we just uploaded all of the artifacts to GS
      # successfully, and can therefore copy them GS->GS, and avoid
      # re-uploading. Publishing is intentionally nested under upload
      # artifacts.
      if publish_info:
        links = self._publish_artifacts(
            target, kind, publish_info, upload_uri, files_by_artifact)
        for k, v in links.items():
          step.presentation.links[k] = v

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
        self.m.gsutil.download(gs_bucket, os.path.join(gs_path, gs_file_name),
                               download_path)
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

  def prepare_for_build(
      self, artifact_types, chroot, sysroot, input_artifacts, name=None):
    """Prepare the build for the given artifacts.

    This function calls the Build API to have it prepare to build artifacts of
    the given types.

    Args:
      artifact_types (list[ArtifactTypes]): List of artifact_types
          to prepare. See build config for options.
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      input_artifacts (list[InputArtifactInfo]): where to seek input artifacts.
      name (str): The step name. Defaults to 'prepare artifacts'.

    Returns:
      PrepareForToolchainBuildResponse.BuildRelevance
    """
    _PREPARE_FUNCS = {
        BuilderConfig.Artifacts.IMAGE_ZIP: self._prepare_unknown,
        BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD: self._prepare_unknown,
        BuilderConfig.Artifacts.AUTOTEST_FILES: self._prepare_unknown,
        BuilderConfig.Artifacts.TAST_FILES: self._prepare_unknown,
        BuilderConfig.Artifacts.PINNED_GUEST_IMAGES: self._prepare_unknown,
        BuilderConfig.Artifacts.FIRMWARE: self._prepare_unknown,
        BuilderConfig.Artifacts.EBUILD_LOGS: self._prepare_unknown,
        BuilderConfig.Artifacts.CHROMEOS_CONFIG: self._prepare_unknown,
        BuilderConfig.Artifacts.CPE_REPORT: self._prepare_unknown,
        BuilderConfig.Artifacts.UNVERIFIED_ORDERING_FILE:
            self._prepare_toolchain,
        BuilderConfig.Artifacts.VERIFIED_ORDERING_FILE: self._prepare_toolchain,
        BuilderConfig.Artifacts.CHROME_CLANG_WARNINGS_FILE:
            self._prepare_toolchain,
        BuilderConfig.Artifacts.UNVERIFIED_LLVM_PGO_FILE:
            self._prepare_toolchain,
        BuilderConfig.Artifacts.UNVERIFIED_CHROME_AFDO_FILE:
            self._prepare_toolchain,
        BuilderConfig.Artifacts.VERIFIED_CHROME_AFDO_FILE:
            self._prepare_toolchain,
        BuilderConfig.Artifacts.VERIFIED_KERNEL_AFDO_FILE:
            self._prepare_toolchain,
    }

    with self.m.step.nest(name or 'prepare artifacts') as step:
      results = []

      funcs_to_call = self._partition_artifacts(artifact_types, _PREPARE_FUNCS)
      for func, types in funcs_to_call.items():
        results.append(func(chroot, sysroot, types, input_artifacts))

      # Return an aggregate response.
      if PrepareForBuildResponse.NEEDED in results:
        step.presentation.step_text = 'Build is NEEDED'
        return PrepareForBuildResponse.NEEDED
      if PrepareForBuildResponse.UNKNOWN in results:
        step.presentation.step_text = 'Build need is UNKNOWN'
        return PrepareForBuildResponse.UNKNOWN
      step.presentation.step_text = 'Build is POINTLESS'
      return PrepareForBuildResponse.POINTLESS
