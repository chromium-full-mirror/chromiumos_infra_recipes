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
        'with the current build config.' %
        BuilderConfig.Artifacts.ArtifactTypes.Name(artifact))
    return getattr(self.m.cros_build_api.ArtifactsService,
                   _LEGACY_ENDPOINTS_BY_ARTIFACT[artifact])

  def _bundle_legacy_artifacts(self, chroot, sysroot, path, artifact_types,
                               _artifact_profile_info):
    """Bundle legacy artifacts.

    Batch handler for legacy artifact types.

    Args:
      chroot (Chroot): The chroot to use.
      sysroot (Sysroot): The sysroot to use.
      path (Path): Path to write bundled artifacts to.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      _artifact_profile_info (ArtifactProfileInfo): profile information.

    Returns:
      dict(artifact_name: list(artifact paths)).  Paths are absolute.
    """
    files_by_artifact = {}
    for artifact in artifact_types:
      name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
      with self.m.step.nest('bundle %s for upload' % name):
        endpoint = self._get_legacy_endpoint(artifact)
        request = artifacts.BundleRequest(chroot=chroot, sysroot=sysroot,
                                          build_target=sysroot.build_target,
                                          output_dir=str(path))
        response = endpoint(request, infra_step=True)

        files_by_artifact[name] = [art.path for art in response.artifacts]
    return files_by_artifact

  def _prepare_pointless(self, _chroot, _sysroot, _artifact_types,
                         _input_artifacts, _artifact_profile_info, test_data):
    """Declare the build necessity POINTLESS from this artifact's perspective.

    Use this prepare_for_build handler for any artifact type which should not
    affect the build decision in the prepare step.  It returns "POINTLESS".

    Args:
      _chroot (Chroot): The chroot to use, or None if not yet created.
      _sysroot (Sysroot): The sysroot to use, or None if not yet created.
      _artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      _input_artifacts (list[InputArtifactInfo]): Where to find input artifacts.
      _artifact_profile_info (ArtifactProfileInfo): profile information.
      _test_data (str): JSON data to use for build API calls.

    Returns:
      (artifacts.PrepareForBuildResponse.build_relevance) POINTLESS.
    """
    return artifacts.PrepareForBuildResponse.POINTLESS

  def _prepare_unknown(self, _chroot, _sysroot, _artifact_types,
                       _input_artifacts, _artifact_profile_info, test_data):
    """Declare the build necessity UNKNOWN from this artifact's perspective.

    Use this prepare_for_build handler for any artifact type which has no
    prepare step.  It returns "UNKNOWN".

    Args:
      _chroot (Chroot): The chroot to use, or None if not yet created.
      _sysroot (Sysroot): The sysroot to use, or None if not yet created.
      _artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      _input_artifacts (list[InputArtifactInfo]): Where to find input artifacts.
      _artifact_profile_info (ArtifactProfileInfo): profile information.
      _test_data (str): JSON data to use for build API calls.

    Returns:
      (artifacts.PrepareForBuildResponse.build_relevance) UNKNOWN.
    """
    return artifacts.PrepareForBuildResponse.UNKNOWN

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
      (artifacts.PrepareForBuildResponse) whether build is necessary.
    """
    req = toolchain.PrepareForToolchainBuildRequest(
        chroot=chroot, sysroot=sysroot, artifact_types=artifact_types,
        input_artifacts=input_artifacts, profile_info=artifact_profile_info)
    resp = self.m.cros_build_api.ToolchainService.PrepareForBuild(
        req, infra_step=True, test_output_data=test_data)
    return resp.build_relevance

  def _bundle_toolchain(self, chroot, sysroot, path, artifact_types,
                        artifact_profile_info):
    """Bundle toolchain artifacts.

    Batch handler for toolchain artifact types.

    Args:
      chroot (Chroot): The chroot to use.
      sysroot (Sysroot): The sysroot to use.
      path (Path): Path to write bundled artifacts to.
      artifact_types (list[ArtifactTypes]): Artifact types to bundle.
      artifact_profile_info (ArtifactProfileInfo): profile information.

    Returns:
      dict(artifact_name: list(artifact paths)).  Paths are absolute.
    """
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

  def _partition_artifacts(self, artifact_types, func_dict, default=None):
    """Partition the artifacts by handler.

    Args:
      artifact_types: (list[ArtifactTypes]): The artifacts to partition.
      func_dict: (dict(artifact_type: function)) Function dictionary.
      default: (func) The function to use for missing artifacts.

    Returns:
      dict(function: list[ArtifactTypes]): each function should be called with
      the given list of artifact types.
    """
    ret = collections.defaultdict(list)
    for art in artifact_types:
      # Some artifact types are only supported in API version 1.1.0, and this
      # method is only called for API version 1.0.0.
      key = func_dict.get(art, default)
      if key:
        ret[key].append(art)
    return ret

  def _bundle_artifacts(self, chroot, sysroot, artifacts_info, outpath,
                        test_data=None):
    """Defer to the build API to bundle the given artifact.

    Args:
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use
      artifacts_info (ArtifactsByService): artifact information.
      outpath (Path): Path to output artifact bundles.
      test_data (str): Some data for this step to return when running under
          simulation.  The string "@@DIR@@" is replaced with the output_dir
          path throughout.

    Returns:
      dict(str: list[str]): Artifact name, list of artifact file paths
          relative to |outpath|.
    """
    if self.m.cros_build_api.is_at_least_version(1, 1, 0):
      return self._bundle_artifacts_110(chroot, sysroot, artifacts_info,
                                        outpath, test_data)
    else:
      return self._bundle_artifacts_100(chroot, sysroot, artifacts_info,
                                        outpath)

  def _bundle_artifacts_110(self, chroot, sysroot, artifacts_info, outpath,
                            test_data):
    """Defer to the build API to bundle the given artifact.

    Args:
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use
      artifacts_info (ArtifactsByService): artifact information.
      outpath (Path): Path to output artifact bundles.
      test_data (str): Some data for this step to return when running under
          simulation.  The string "@@DIR@@" is replaced with the output_dir
          path throughout.

    Returns:
      dict(str: list[str]): Artifact name, list of artifact file paths
          relative to |outpath|.
    """
    outdir = str(outpath)
    req = artifacts.BundleArtifactsRequest(chroot=chroot, sysroot=sysroot,
                                           artifact_info=artifacts_info,
                                           output_dir=outdir)

    test_data = None if not test_data else test_data.replace('@@DIR@@', outdir)
    try:
      resp = self.m.cros_build_api.ArtifactsService.BundleArtifacts(
          req, infra_step=True, test_output_data=test_data)
    except Exception as e:  # pragma: nocover
      self.m.disk_usage.track(step_name='track disk usage', depth=0)
      self.m.disk_usage.track(step_name='track disk usage', depth=1,
                              dir='/b/s/w/')
      raise e

    # Create files_by_artifact.
    files_by_artifact = {}
    for service in json_format.MessageToDict(resp.artifacts).values():
      for paths in service.get('artifacts', []):
        files_by_artifact[paths['artifactType']] = [
            os.path.relpath(f, outdir) for f in paths['paths']
        ]

    return files_by_artifact

  def _bundle_artifacts_100(self, chroot, sysroot, artifacts_info, outpath):
    """Defer to the build API (version 1.0.0) to bundle the given artifact.

    Args:
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use
      artifacts_info (ArtifactsByService): artifact information.
      outpath (Path): Path to output artifact bundles.

    Returns:
      dict(str: list[str]): Artifact name, list of artifact file paths
          relative to |outpath|.
    """
    atype = BuilderConfig.Artifacts
    _BUNDLE_FUNCS = {
        atype.IMAGE_ZIP: self._bundle_legacy_artifacts,
        atype.TEST_UPDATE_PAYLOAD: self._bundle_legacy_artifacts,
        atype.AUTOTEST_FILES: self._bundle_legacy_artifacts,
        atype.TAST_FILES: self._bundle_legacy_artifacts,
        atype.PINNED_GUEST_IMAGES: self._bundle_legacy_artifacts,
        atype.FIRMWARE: self._bundle_legacy_artifacts,
        atype.EBUILD_LOGS: self._bundle_legacy_artifacts,
        atype.CHROMEOS_CONFIG: self._bundle_legacy_artifacts,
        atype.CPE_REPORT: self._bundle_legacy_artifacts,
        atype.IMAGE_ARCHIVES: self._bundle_legacy_artifacts,
        atype.UNVERIFIED_CHROME_LLVM_ORDERFILE: self._bundle_toolchain,
        atype.VERIFIED_CHROME_LLVM_ORDERFILE: self._bundle_toolchain,
        atype.CHROME_CLANG_WARNINGS_FILE: self._bundle_toolchain,
        atype.UNVERIFIED_LLVM_PGO_FILE: self._bundle_toolchain,
        atype.UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE: self._bundle_toolchain,
        atype.VERIFIED_CHROME_BENCHMARK_AFDO_FILE: self._bundle_toolchain,
        atype.UNVERIFIED_KERNEL_CWP_AFDO_FILE: self._bundle_toolchain,
        atype.VERIFIED_KERNEL_CWP_AFDO_FILE: self._bundle_toolchain,
        atype.UNVERIFIED_CHROME_CWP_AFDO_FILE: self._bundle_toolchain,
        atype.VERIFIED_CHROME_CWP_AFDO_FILE: self._bundle_toolchain,
        atype.VERIFIED_RELEASE_AFDO_FILE: self._bundle_toolchain,
        atype.UNVERIFIED_CHROME_BENCHMARK_PERF_FILE: self._bundle_toolchain,
        atype.CHROME_DEBUG_BINARY: self._bundle_toolchain,
    }

    # Create artifact_types.
    artifact_types = []
    for _, service in artifacts_info.ListFields():
      for art_info in getattr(service, 'output_artifacts', []):
        artifact_types.extend(art_info.artifact_types)

    outdir = str(outpath)
    files = {}
    funcs = self._partition_artifacts(artifact_types, _BUNDLE_FUNCS)
    try:
      # Sorting is done here only to give us consistency in the expected.json
      # for our tests.
      for func, types in sorted(funcs.items(), key=lambda x: x[0].__name__):
        files.update(
            func(chroot, sysroot, outpath, types, artifacts_info.profile_info))
    except Exception as e:  # pragma: nocover
      self.m.disk_usage.track(step_name='track disk usage', depth=0)
      self.m.disk_usage.track(step_name='track disk usage', depth=1,
                              dir='/b/s/w/')
      raise e

    return {
        k: [os.path.relpath(f, outdir) for f in v] for k, v in files.items()
    }

  def _artifacts_gs_path_dict(self, builder_name, target, kind):
    """Returns the dictionary tokens for expanding location templates.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
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
        'builder_name': builder_name.lower().replace('_', '-'),
    }
    ret['gs_path'] = '%s/%s-%d' % (ret['builder_name'], ret['version'],
                                   ret['build_id'])
    return ret

  def artifacts_gs_path(self, builder_name, target, kind):
    """Returns the GS path for artifacts of the given kind for the given target.

    The resulting path will NOT include the GS bucket.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. Used as a descriptor in the GS path.

    Returns:
      The GS path at which artifacts should be uploaded.
    """
    return self._artifacts_gs_path_dict(builder_name, target, kind)['gs_path']

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
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
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
            if files:
              location_dict['artifact_name'] = aname
              publish_loc = publish_template.format(location_dict)
              link_name = 'gs publish dir: %s' % aname
              link_value = (
                  'https://console.cloud.google.com/storage/browser/%s' %
                  publish_loc)
              links[link_name] = link_value
              presentation.links[link_name] = link_value
              publish_uri = 'gs://' + publish_loc
              if not publish_uri.endswith('/'):
                publish_uri += '/'
              cmd = ['cp']
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
                  else:
                    raise
              published[aname].append({
                  'gs_location': publish_loc,
                  'files': files
              })

      self.m.easy.set_property_step('published', published,
                                    step_name='publish artifact GS paths')

      return links

  def upload_artifacts(self, builder_name, target, kind, gs_bucket,
                       artifacts_info=None, chroot=None, sysroot=None,
                       name=None, test_data=None):
    """Bundle and upload the given artifacts for the given build target.

    This function sets the "artifacts" output property to include the
    GS bucket, the path within that bucket, and a dict mapping artifact
    to a list of artifact paths (relative to the GS path) for each artifact
    type that was uploaded.

    Args:
      builder_name (str): The builder name, e.g. octopus-cq.
      target (BuildTarget): The build target with artifacts of interest.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
          Google Storage.
      gs_bucket (str): Google storage bucket to upload artifacts to.
      artifacts_info (ArtifactsByService): Information about artifacts.
      chroot (Chroot): chroot to use
      sysroot (Sysroot): sysroot to use
      name (str): The step name. Defaults to 'upload artifacts'.
      test_data (str): Some data for this step to return when running under
          simulation.  The string "@@DIR@@" is replaced with the output_dir
          path throughout.
    """
    with self.m.step.nest(name or 'upload artifacts') as presentation:
      outpath = self.m.path.mkdtemp(prefix='artifacts')
      files_by_artifact = self._bundle_artifacts(chroot, sysroot,
                                                 artifacts_info, outpath,
                                                 test_data)

      # Upload all of the artifacts to the archive bucket/path.
      gs_path = self.artifacts_gs_path(builder_name, target, kind)
      presentation.links['gs upload dir'] = (
          'https://console.cloud.google.com/storage/browser/%s/%s' %
          (gs_bucket, gs_path))
      upload_uri = 'gs://%s/%s' % (gs_bucket, gs_path)
      for retries in range(3):
        try:
          self.m.gsutil(['rsync', outpath, upload_uri], parallel_upload=True,
                        multithreaded=True,
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
      links = self._publish_artifacts(builder_name, target, kind,
                                      artifacts_info, upload_uri,
                                      files_by_artifact)
      for k, v in links.items():
        presentation.links[k] = v

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
      is NEEDED (regardless of the pointless build check), UNKNOWN (pointless
      build check applies), or POINTLESS (just exit now.)
    """
    with self.m.step.nest(name or 'prepare artifacts') as presentation:
      if self.m.cros_build_api.is_at_least_version(1, 1, 0):
        ret = self.m.cros_build_api.ArtifactsService.PrepareForBuild(
            artifacts.PrepareForBuildRequest(
                chroot=chroot, sysroot=sysroot, artifact_info=artifacts_info,
                forced_build_relevance=forced_build_relevance), infra_step=True,
            test_output_data=test_data).build_relevance
      else:
        ret = self._prepare_for_build_100(chroot, sysroot, artifacts_info,
                                          test_data=test_data)

      if ret == artifacts.PrepareForBuildResponse.NEEDED:
        presentation.step_text = 'Build is NEEDED'
      elif ret == artifacts.PrepareForBuildResponse.UNKNOWN:
        presentation.step_text = 'Build need is UNKNOWN'
      else:
        presentation.step_text = 'Build is POINTLESS'
    return ret

  def _prepare_for_build_100(self, chroot, sysroot, artifacts_info,
                             test_data=None):
    """Prepare the build for the given artifacts, using Build API version 1.0.0.

    This function calls the Build API to have it prepare to build artifacts of
    the given types.

    Args:
      chroot (Chroot): The chroot to use, or None if not yet created.
      sysroot (Sysroot): The sysroot to use, or None if not yet created.
      artifacts_info (ArtifactsByService): artifact information.
      test_data (str): JSON data to use for build API calls.

    Returns:
      PrepareForToolchainBuildResponse.BuildRelevance indicating that the build
      is NEEDED (regardless of the pointless build check), UNKNOWN (pointless
      build check applies), or POINTLESS (just exit now.)
    """
    # By default, artifacts will get 'UNKNOWN'.
    # EBUILD_LOGS are not relevant.
    atype = BuilderConfig.Artifacts
    _PREPARE_FUNCS = {
        atype.EBUILD_LOGS: self._prepare_pointless,
        atype.UNVERIFIED_CHROME_LLVM_ORDERFILE: self._prepare_toolchain,
        atype.VERIFIED_CHROME_LLVM_ORDERFILE: self._prepare_toolchain,
        atype.CHROME_CLANG_WARNINGS_FILE: self._prepare_toolchain,
        atype.UNVERIFIED_LLVM_PGO_FILE: self._prepare_toolchain,
        atype.UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE: self._prepare_toolchain,
        atype.VERIFIED_CHROME_BENCHMARK_AFDO_FILE: self._prepare_toolchain,
        atype.UNVERIFIED_KERNEL_CWP_AFDO_FILE: self._prepare_toolchain,
        atype.VERIFIED_KERNEL_CWP_AFDO_FILE: self._prepare_toolchain,
        atype.UNVERIFIED_CHROME_CWP_AFDO_FILE: self._prepare_toolchain,
        atype.VERIFIED_CHROME_CWP_AFDO_FILE: self._prepare_toolchain,
        atype.VERIFIED_RELEASE_AFDO_FILE: self._prepare_toolchain,
        atype.UNVERIFIED_CHROME_BENCHMARK_PERF_FILE: self._prepare_toolchain,
        atype.CHROME_DEBUG_BINARY: self._prepare_toolchain,
    }

    # We need to use the 1.0.0 method.  Create artifact_types and
    # input_artifacts for the call.
    artifact_types = []
    input_artifacts = []
    for _, service in artifacts_info.ListFields():
      # artifact_types is the list of output artifact types.
      for out_art in getattr(service, 'output_artifacts', []):
        artifact_types.extend(out_art.artifact_types)

      # input_artifacts is the list of input_artifacts, rewritten into the
      # correct message type.
      for in_art in getattr(service, 'input_artifacts', []):
        for atype in in_art.artifact_types:
          input_artifacts.append(
              BuilderConfig.Artifacts.InputArtifactInfo(
                  input_artifact_type=atype,
                  input_artifact_gs_locations=in_art.gs_locations))

    funcs = self._partition_artifacts(artifact_types, _PREPARE_FUNCS,
                                      self._prepare_unknown)

    # If there are no prepare functions to call: Build need is UNKNOWN.
    if not funcs:
      return artifacts.PrepareForBuildResponse.UNKNOWN

    result = artifacts.PrepareForBuildResponse.POINTLESS
    # Sorting is done here only to give us consistency in the expected.json
    # for our tests.
    for func, types in sorted(funcs.items(), key=lambda x: x[0].__name__):
      res = func(chroot, sysroot, types, input_artifacts,
                 artifacts_info.profile_info, test_data=test_data)
      # If this func says NEEDED, or the result so far is POINTLESS, then the
      # result is what this func said.
      if (res == artifacts.PrepareForBuildResponse.NEEDED or
          result == artifacts.PrepareForBuildResponse.POINTLESS):
        result = res

    return result
