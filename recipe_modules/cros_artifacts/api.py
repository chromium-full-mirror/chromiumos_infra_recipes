# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

import collections

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromite.api import artifacts
from PB.chromite.api import toolchain
from PB.chromite.api.image import PushImageRequest, PushImageResponse
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos import common as common_pb
from PB.chromiumos.common import ArtifactsByService

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
    BuilderConfig.Artifacts.FPMCU_UNITTESTS: 'BundleFpmcuUnittests',
    BuilderConfig.Artifacts.GCE_TARBALL: 'BundleGceTarball',
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
    name = _LEGACY_ENDPOINTS_BY_ARTIFACT[artifact]
    return (getattr(self.m.cros_build_api.ArtifactsService, name)
            if self.m.cros_build_api.has_endpoint(
                self.m.cros_build_api.ArtifactsService, name) else None)

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
        response = artifacts.BundleResponse()
        if endpoint:
          request = artifacts.BundleRequest(chroot=chroot, sysroot=sysroot,
                                            build_target=sysroot.build_target,
                                            output_dir=str(path))
          response = endpoint(request, infra_step=True)

        files_by_artifact[name] = [art.path for art in response.artifacts]
    return files_by_artifact

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
      test_data (str): JSON data to use for build API calls.

    Returns:
      (artifacts.PrepareForBuildResponse.build_relevance) UNKNOWN.
    """
    # Noop statement to clean up pylint.
    test_data = test_data or None
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
      self.m.disk_usage.track(step_name='track disk usage', depth=2,
                              dir=self.m.path['cache'])
      raise e

    # Create files_by_artifact.
    files_by_artifact = {}
    for service in json_format.MessageToDict(resp.artifacts).values():
      for paths in service.get('artifacts', []):
        files_by_artifact[paths['artifactType']] = [
            self.m.path.relpath(f['path'], outpath) for f in paths['paths']
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
    funcs = collections.defaultdict(list)
    for _, service in artifacts_info.ListFields():
      for art_info in getattr(service, 'output_artifacts', []):
        if service.DESCRIPTOR.name == 'Toolchain':
          funcs[self._bundle_toolchain].extend(art_info.artifact_types)
        else:
          # If it's not Toolchain, then it's legacy.  1.0.0 only supports those
          # two services having artifacts.
          funcs[self._bundle_legacy_artifacts].extend(art_info.artifact_types)

    outdir = str(outpath)
    files = {}
    try:
      # Sorting is done here only to give us consistency in the expected.json
      # for our tests.
      for func, types in sorted(funcs.items(), key=lambda x: x[0].__name__):
        files.update(
            func(chroot, sysroot, outpath, types, artifacts_info.profile_info))
    except Exception as e:  # pragma: nocover
      self.m.disk_usage.track(step_name='track disk usage', depth=0)
      self.m.disk_usage.track(
          step_name='track disk usage', depth=1,
          dir='/'.join(str(self.m.path['cache']).split('/')[:-2]))
      raise e

    return {
        k: [self.m.path.relpath(f, outpath) for f in v
           ] for k, v in files.items()
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
                         upload_uri, files_by_artifact, name=None,
                         failing_build=False):
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
      failing_build (bool): whether or not the build is failing, used (in part)
          to decide whether or not to upload artifacts.

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
        if out_info.get('gsLocations') and out_info.get('artifactTypes') and (
            not failing_build or
            out_info.get('publishCondition') == ArtifactsByService
            .PublishCondition.Name(ArtifactsByService.PUBLISH_ALWAYS)):
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

      self.m.easy.set_properties_step(published=published,
                                      step_name='publish artifact GS paths')

      return links

  def has_output_artifacts(self, artifacts_info):
    """Return whether there are output artifacts.

    Args:
      artifacts (ArtifactsByService): The artifacts config to check.

    Returns:
      (bool) whether there are any output artifacts.
    """
    # Iterate over the components of artifacts_info, and return true if there
    # are any output_artifacts with artifact_types.
    for _, service in artifacts_info.ListFields():
      for art_info in getattr(service, 'output_artifacts', []):
        if art_info.artifact_types:
          return True
    return False

  def upload_artifacts(self, builder_name, target, kind, gs_bucket,
                       artifacts_info=None, chroot=None, sysroot=None,
                       failing_build=False, name=None, test_data=None):
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
      failing_build (bool): whether or not the build is failing, used (in part)
          to decide whether or not to upload artifacts.
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

      if not files_by_artifact:
        presentation.step_text = 'No artifacts found.'
        return

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

      self.m.easy.set_properties_step(
          artifacts={
              'gs_bucket': gs_bucket,
              'gs_path': gs_path,
              'files_by_artifact': files_by_artifact,
          }, step_name='output artifact GS paths')

      # We upload artifacts whether the build passed or failed (see
      # crbug/1086630).
      #
      # Publishing artifacts is a "Push to Production" step.  As such,
      # dry-run and failed builds must not publish artifacts.  However,
      # there are some cases in which we'd like to publish artifacts for
      # failed builds (e.g. CLANG_CRASH_DIAGNOSES). As such, we pass
      # failing_build to _publish_artifacts and publish if the build is
      # not failing or if ArtifactInfo.publish_conditions = PUBLISH_ALWAYS.

      # Builders that publish artifacts should not recycyle dry-run builds,
      # since we treat them differently here.
      if self.m.cq.state == self.m.cq.DRY:
        with self.m.step.nest('skip publish artifacts') as presentation:
          presentation.step_text = 'Not publishing artifacts in dry run'
          return

      # Now publish any artifacts that have publishing information.  This is
      # done here (rather than adding api.cros_artifacts.publish_artifacts)
      # because we know that we just uploaded all of the artifacts to GS
      # successfully, and can therefore copy them GS->GS, and avoid
      # re-uploading. Publishing is intentionally nested under upload
      # artifacts.
      links = self._publish_artifacts(builder_name, target, kind,
                                      artifacts_info, upload_uri,
                                      files_by_artifact,
                                      failing_build=failing_build)
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

      self.m.easy.set_properties_step(
          artifact_prep=json_format.MessageToDict(
              artifacts.PrepareForBuildResponse(build_relevance=ret)),
          step_name='set artifact_prep')
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
    _IGNORE_ARTIFACT_TYPES = [atype.EBUILD_LOGS]

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
          input_artifacts.append(
              BuilderConfig.Artifacts.InputArtifactInfo(
                  input_artifact_type=atype,
                  input_artifact_gs_locations=in_art.gs_locations))

    # If there are no prepare functions to call: Build need is UNKNOWN.
    if not funcs:
      return artifacts.PrepareForBuildResponse.UNKNOWN

    result = artifacts.PrepareForBuildResponse.POINTLESS
    # Sorting is done here only to give us consistency in the expected.json
    # for our tests.
    with self.m.step.nest('call prepare funcs') as pres:
      for func, types in sorted(funcs.items(), key=lambda x: x[0].__name__):
        res = func(chroot, sysroot, types, input_artifacts,
                   artifacts_info.profile_info, test_data=test_data)
        pres.logs[func.__name__] = '%s => %s' % ([
            BuilderConfig.Artifacts.ArtifactTypes.Name(x) for x in types
        ], artifacts.PrepareForBuildResponse.BuildRelevance.Name(res))
        # If this func says NEEDED, or the result so far is POINTLESS, then the
        # result is what this func said.
        if (res == artifacts.PrepareForBuildResponse.NEEDED or
            result == artifacts.PrepareForBuildResponse.POINTLESS):
          result = res

    return result

  def push_image(self, chroot, gs_image_dir, sysroot, dryrun=False,
                 profile=None, sign_types=None, dest_bucket=None):
    """Call the PushImage build API endpoint.

      Args:
        chroot (Chroot): The chroot to use, or None if not yet created.
        gs_image_dir (string): The source directory (a gs path) to push from.
        sysroot (Sysroot): The sysroot (build target) to use.
        profile (Profile): The profile to use, or None.
        sign_types (list(ImageType)): The sign types to use, or None.

        For more context on this parameters, see chromite/scripts/pushimage.py.
      """
    request = PushImageRequest(
        chroot=chroot,
        gs_image_dir=gs_image_dir,
        sysroot=sysroot,
        dryrun=dryrun,
        profile=profile,
        sign_types=sign_types,
        dest_bucket=dest_bucket,
    )
    self.m.cros_build_api.ImageService.PushImage(request, test_output_data='{}')
