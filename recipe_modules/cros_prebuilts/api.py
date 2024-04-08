# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS prebuilts to Google Storage."""

import os
import datetime
from typing import Dict, List, Optional, Tuple

from google.protobuf import json_format

from PB.chromite.api import binhost as binhost_pb
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.chromiumos.common import PackageIndexInfo
from PB.chromiumos.common import Path
from PB.chromiumos.common import Profile
from recipe_engine import recipe_api

from RECIPE_MODULES.recipe_engine.time.api import exponential_retry
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

# The trailing / is for gsutil rsync.
METADATA_GS_DIR_TMPL = 'gs://{gs_bucket}/snapshot/{snapshot}/{target}/{profile}/'
METADATA_GS_FILE_TMPL = '{builder}-{build_id}-{kind}.json'

GIT_PUSH_MAX_RETRY_COUNT = 3


class CrosPrebuiltsApi(recipe_api.RecipeApi):
  """A module for uploading package prebuilts."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._use_staging_branch = properties.use_staging_branch
    self._enable_snapshot_prebuilts = properties.enable_snapshot_prebuilts
    self._send_snapshot_prebuilts = properties.send_snapshot_prebuilts
    self._commit_overlay_binhost = properties.commit_overlay_binhost
    self._max_binhost_uris = properties.max_binhost_uris
    if not self._max_binhost_uris:
      self._max_binhost_uris = 1

  @property
  def _build_id(self):
    """Get our build id, or swarming task_id."""
    return str(self.m.buildbucket.build.id or
               'led_%s' % self.m.swarming.task_id)

  def _profile_or_default(self, profile):
    """Return a default profile if there is no profile."""
    return profile if profile and profile.name else Profile(name='base')

  def _prebuilts_uri(self, target: BuildTarget, kind: BuilderConfig.Id.Type,
                     gs_bucket: str, profile: Optional[Profile] = None) -> str:
    """Determine the GS URI to upload prebuilts to.

    Args:
      target: The build target.
      kind: The kind of prebuilts, e.g. POSTSUBMIT
      gs_bucket: Google storage bucket to upload prebuilts to.
      profile: The Profile, or None for the default "base" profile.

    Returns:
      The full GS URI in which to upload prebuilts.
    """
    target_label = target.name
    if profile is not None and profile.name and profile.name != 'base':
      target_label = f'{target_label}-{profile.name}'
    kind_label = BuilderConfig.Id.Type.Name(kind).lower()
    version = self.m.cros_version.version
    return f'gs://{gs_bucket}/board/{target_label}/{kind_label}-{version}-{self._build_id}/packages'

  def _devinstall_prebuilts_uri(self, target, gs_bucket, staging=False):
    """Determine the GS URI to upload devinstall prebuilts.

    Args:
      target (BuildTarget): The build target.
      gs_bucket (str): Google storage bucket to upload devinstall prebuilts to.

    Returns:
      The full GS URI in which to upload devinstall prebuilts.
    """
    version = self.m.cros_version.version.platform_version
    # Since there is not a strong guarantee that staging configuration will
    # provide a bucket that is used only for this purpose, if this is running in
    # staging play it safe and create another directory specifically for the
    # devinstall prebuilts to help find staging artifacts.
    bucket_suffix = '/devinstall_prebuilts' if staging else ''
    return 'gs://%s%s/board/%s/%s/packages' % (gs_bucket, bucket_suffix,
                                               target.name, version)

  def _get_host_prebuilts_dest(self, target: BuildTarget,
                               kind: BuilderConfig.Id.Type,
                               build_id: str) -> str:
    """Determine the GS destination in a bucket to upload host prebuilts to.

    Args:
      target: The build target.
      kind: The kind of prebuilts, e.g. POSTSUBMIT
      build_id: The buildbucket id or swarming task id.

    Returns:
      The GS destination in which to upload prebuilts.
    """
    target_name = target.name
    kind_label = BuilderConfig.Id.Type.Name(kind).lower()
    version = self.m.cros_version.version
    return f'host/amd64/{target_name}/{kind_label}-{version}-{build_id}/packages'

  def _upload_metadata(self, build_target, profile, kind, gs_bucket, acls,
                       location):
    """Upload metadata about the (uploaded) prebuilts.

    Args:
      build_target (BuildTarget): The build target.
      profile (chromiumos.Profile): The profile for the build.
      kind (BuilderConfig.Id.Type): The kind of prebuilts, e.g. POSTSUBMIT
      gs_bucket (str): Google storage bucket to upload prebuilts to.
      acls: (List[AclArg]): acls to apply to the uploaded metadata, will be
          empty if the prebuilts are public.
      location (str): The Google Storage URI where the prebuilts were uploaded.
    """
    with self.m.step.nest('upload metadata'):
      version = self.m.cros_version.version
      commit = self.m.cros_infra_config.gitiles_commit
      target = build_target.name if build_target else 'Unknown'

      metadata = PackageIndexInfo(snapshot_sha=commit.id, profile=profile,
                                  snapshot_number=version.snapshot,
                                  build_target=build_target, location=location)
      metadata_file = self.m.path.mkdtemp(
          prefix='metadata').join('PackageIndexInfo.json')

      metadata_json = json_format.MessageToJson(metadata,
                                                use_integers_for_enums=True)
      self.m.file.write_text('write metadata', metadata_file,
                             '%s\n' % metadata_json)

      snapshot_strs = [commit.id]

      with self.m.context(cwd=self.m.src_state.build_manifest.path):
        snapshot_identifier = self.m.git_footers.from_ref(
            commit.id, key='Cr-Snapshot-Identifier',
            step_test_data=self.m.git_footers.test_api.step_test_data_factory(
                '5555'))
        if snapshot_identifier:
          snapshot_strs.append('{}-id-{}'.format(self.m.src_state.manifest_name,
                                                 snapshot_identifier[0]))
      for snapshot_str in snapshot_strs:
        tmpl = os.path.join(METADATA_GS_DIR_TMPL, METADATA_GS_FILE_TMPL)
        uri = tmpl.format(
            build_id=self._build_id,
            builder=self.m.buildbucket.build.builder.builder,
            gs_bucket=gs_bucket,
            kind=BuilderConfig.Id.Type.Name(kind).lower(),
            profile=profile.name,
            snapshot=snapshot_str,
            target=target,
        )
        self.m.gsutil(['cp', metadata_file, uri])
        cmd = ['acl', 'ch']
        self._add_acls(acls, cmd)
        cmd.append(uri)
        self.m.gsutil(cmd)

  def _publish_binhost_metadata(self, build_target: BuildTarget,
                                profile: Profile, gs_uri: str,
                                gs_bucket_name: str, complete: bool,
                                private: bool):
    """Publish binhost metadata using the binhost_lookup_service module.

    Args:
      build_target: The system CrOS is being built for, also known as board.
      profile: Profile to use with the build_target.
      gs_uri: Location of the binhost object in google storage.
      gs_bucket_name: Name of the google storage bucket which contains the
          binhost.
      complete: Bool to indicate if this binhost contains all the binpkgs
          specified in the packages metadata file.
      private: Bool to indicate if the binhost is private.
    """
    with self.m.step.nest('publish binhost metadata'):
      snapshot_sha = self.m.cros_infra_config.gitiles_commit.id
      self.m.binhost_lookup_service.publish_binhost_metadata(
          build_target, profile, snapshot_sha, gs_uri, gs_bucket_name,
          self.m.buildbucket.build.id, complete, private)

  def _binhost_key(self, kind):
    """Return the binhost key for the given builder type.

    Args:
      kind (BuilderConfig.Id.Type): The builder type.

    Returns:
      BinhostKey: The binhost key.

    Raises:
      ValueError: If prebuilts are not supported for the given builder type.
    """
    name = BuilderConfig.Id.Type.Name(kind)
    try:
      return binhost_pb.BinhostKey.Value('%s_BINHOST' % name.upper())
    except ValueError as err:
      err.message = '%s builders may not upload prebuilts' % name.lower()
      raise

  def _parse_binhost(self, binhost):
    """Parses binhost into bucket and full file path parts.

    Parses the google storage URIs as provided in the binhost.uri field into
    their respective bucket and full file path parts.

    Args:
      binhost (Binhost): binhost to parse.

    Returns:
      tuple(str, str): google storage bucket and full file path.
    """
    assert binhost.uri.startswith('gs://'), (
        'binhosts URI %s does not appear to be a google storage path' %
        binhost.uri)
    uri = binhost.uri[len('gs://'):]
    parts = uri.split('/', 1)
    assert len(parts) == 2, '%s would not split into bucket and path' % uri
    return parts[0], os.path.join(parts[1], binhost.package_index)

  def _get_binhosts(self, target, chroot, private):
    """Download binhost files from google storage.

    Download binhost files from google storage and returns PackageInfo files
    specifying their location.

    Args:
      target (BuildTarget): Build target getting binhosts for.
      chroot (chromiumos.common.Chroot): Chroot to work with.
      private (bool): whether to include private binhosts.

    Returns:
      List[PackageInfo]: Package info files to deduplicate the prebuilt list.
    """
    with self.m.step.nest('get binhosts'):
      request = binhost_pb.BinhostGetRequest(build_target=target, chroot=chroot,
                                             private=private)
      response = self.m.cros_build_api.BinhostService.Get(
          request, infra_step=True)
      binhosts_root = self.m.path.mkdtemp(prefix='binhosts')
      package_index_files = []
      for b in response.binhosts:
        gs_bucket, gs_source = self._parse_binhost(b)
        dest = binhosts_root.join(gs_source)
        self.m.gsutil.download(gs_bucket, gs_source, dest)
        package_index_files.append(
            binhost_pb.PackageIndex(
                path=Path(path=str(dest), location=Path.OUTSIDE)))
      return package_index_files

  def _prepare_binhost_uploads(self, sysroot, chroot, uri, package_index_files):
    """Determine which prebuilt archives should be uploaded to the binhost.

    Args:
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      chroot (chromiumos.common.Chroot): Chroot to work with.
      uri (str): URI where prebuilts will be uploaded.
      package_index_files (List[PackageIndex]): package index files to
          deduplicate the prebuilt list.

    Returns:
      tuple(Path, List[str]): Path to directory containing uploads and
          a list of uploadable string paths relative to that directory.
    """
    with self.m.step.nest('prepare binhost uploads'):
      request = binhost_pb.PrepareBinhostUploadsRequest(
          sysroot=sysroot, uri=uri, package_index_files=package_index_files,
          chroot=chroot)
      response = self.m.cros_build_api.BinhostService.PrepareBinhostUploads(
          request, infra_step=True)
      upload_root = self.m.path.abs_to_path(response.uploads_dir)
      upload_paths = [ut.path for ut in response.upload_targets]
      return upload_root, upload_paths

  def _prepare_devinstall_binhost_uploads(self, sysroot, uri, chroot):
    """Get the prebuilts from the build-api into a local directory.

    Args:
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      uri (str): URI where prebuilts will be uploaded.

    Returns:
      tuple(Path, List[str]): Path to directory containing uploads and
          a list of uploadable string paths relative to that directory.
    """
    with self.m.step.nest('prepare dev_install binhost uploads'):
      upload_root = self.m.path.mkdtemp(prefix='binhosts')
      request = binhost_pb.PrepareDevInstallBinhostUploadsRequest(
          sysroot=sysroot, uploads_dir=self.m.path.abspath(upload_root),
          uri=uri, chroot=chroot)
      response = self.m.cros_build_api.BinhostService.PrepareDevInstallBinhostUploads(
          request, infra_step=True)
      upload_paths = [ut.path for ut in response.upload_targets]
      return upload_root, upload_paths

  def _prepare_chrome_binhost_uploads(self, sysroot: Sysroot, chroot: Chroot,
                                      uri: str) -> Tuple[Path, List[str]]:
    """Get the Chrome prebuilts that should be uploaded to the binhost.

    Args:
      sysroot: The sysroot whose prebuilts are being uploaded.
      chroot: Chroot to work with.
      uri: URI where the prebuilts will be uploaded.

    Returns:
      (Path to the directory containing uploads,
          a list of uploadable string paths relative to that directory)
    """
    with self.m.step.nest('prepare chrome binhost uploads'):
      upload_root = self.m.path.mkdtemp(prefix='binhosts')
      request = binhost_pb.PrepareChromeBinhostUploadsRequest(
          sysroot=sysroot, chroot=chroot,
          uploads_dir=self.m.path.abspath(upload_root), uri=uri)
      response = self.m.cros_build_api.BinhostService.PrepareChromeBinhostUploads(
          request, infra_step=True)
      upload_paths = [target.path for target in response.upload_targets]
      return upload_root, upload_paths

  def set_binhosts(
      self, binhosts: List[Tuple[BuildTarget, str]], private: bool,
      key: binhost_pb.BinhostKey,
      overriding_max_uris: Optional[Dict[str, int]] = None) -> None:
    """Set the target's Portage binhosts to point to the given URIs.

    This function updates a conf file within the target's overlay, commits the
    change, and pushes it.

    Args:
      binhosts: List of tuples of build targets and their new URIs.
      private: Whether the target's binhost is private.
      key: The binhost key, e.g. POSTSUBMIT_BINHOST.
      overriding_max_uris: Dict to override `max_uris` for board. Key is the
          name of build target, Value is the number of `max_uris` used for the
          build target. None for using the default value.
    """

    if len(binhosts) == 0:
      raise recipe_api.StepFailure('binhosts must not be empty')

    # In order to avoid any merge conflicts we first pull the latest changes
    # from remote, update the conf flie locally, and then push the
    # changes remotely.
    binhost_path = self._get_binhost_path(binhosts[0][0], private, key)
    project = self.m.repo.project_info(
        project=self.m.path.dirname(binhost_path))
    with self.m.context(
        cwd=self.m.cros_source.workspace_path.join(project.path)):
      branch = project.branch
      if branch:
        # The unit tests needs the ebuilds to be the same version we build them
        # at. so after we pull the latest and commit our changes, we checkout
        # the commit from which we started. Here we are saving the current
        # commit so we can checkout again after we push our updates.
        current_commit = self.m.git.head_commit()

        # Staging doesn't have ACLs to push conf files to the real branch.
        # Instead, use a branch with the last component named 'staging'
        if self._use_staging_branch:
          branch_parts = branch.split('/')
          branch_parts[-1] = 'staging'
          branch = '/'.join(branch_parts)

        self.set_binhosts_retry(binhosts, private, key, project, branch,
                                overriding_max_uris)
        self.m.git.checkout(current_commit)

  # There are instances when, in between fetching from remote and
  # then committing our changes, a different builder can commit its changes.
  # This can cause merging issues (see ex: http://shortn/_WtgjVa2ayK).
  # We can retry few times to avoid it.
  @exponential_retry(retries=GIT_PUSH_MAX_RETRY_COUNT,
                     delay=datetime.timedelta(seconds=1))
  def set_binhosts_retry(
      self, binhosts: List[Tuple[BuildTarget, str]], private: bool,
      key: binhost_pb.BinhostKey, target_project: ProjectInfo, branch: str,
      overriding_max_uris: Optional[Dict[str, int]] = None) -> None:
    """Utility method to update the target's Portage binhosts.

    This function is intended to be called from set_binhosts.

    Args:
      binhosts: List of tuples of build targets and their new URIs.
      private: Whether the target's binhost is private.
      key: The binhost key, e.g. POSTSUBMIT_BINHOST.
      target_project: Project of the binhosts.
      branch: branch name to update
      overriding_max_uris: Dict to override `max_uris` for board. Key is the
          name of build target, Value is the number of `max_uris` used for the
          build target. None for using the default value.
    """
    if len(binhosts) == 0:
      return

    self.m.git.fetch_ref(target_project.remote, branch)
    self.m.git.checkout('FETCH_HEAD', force=True)

    overriding_max_uris = overriding_max_uris or {}

    commit_message = []
    binhost_changes = []
    for (target, uri) in binhosts:
      with self.m.step.nest(f'update {target.name}') as presentation:
        max_uris = overriding_max_uris.get(target.name, self._max_binhost_uris)

        request = binhost_pb.SetBinhostRequest(build_target=target,
                                               private=private, key=key,
                                               uri=uri, max_uris=max_uris)
        response = self.m.cros_build_api.BinhostService.SetBinhost(
            request, infra_step=True)
        binhost_path = response.output_file

        # All binhosts must be in the same project.
        current_project = self.m.repo.project_info(
            project=self.m.path.dirname(binhost_path))
        if target_project != current_project:
          presentation.step_text = \
              'The project is different from the first one.'
          presentation.logs['project of this binhost'] = str(current_project)
          presentation.logs['project of first binhost'] = str(target_project)
          continue

        # Read and output the BINHOST.conf file contents
        binhost_content = self.m.file.read_text('read binhost conf',
                                                binhost_path)
        binhost_changes.append((binhost_path, binhost_content))
        commit_message.extend([
            'Set %s=%s.' % (binhost_pb.BinhostKey.Name(key), uri),
            'go/bbid/%s' % self._build_id,
            '',
        ])

    with self.m.step.nest('create change') as presentation:
      if len(binhost_changes) == 0:
        presentation.step_text = 'No changes on binhosts'
        return

      self.m.git_txn.update_ref_write_files(target_project.remote,
                                            '\n'.join(commit_message),
                                            binhost_changes, automerge=True,
                                            ref=branch)

  def _get_binhost_path(self, build_target: BuildTarget, private: bool,
                        key: binhost_pb.BinhostKey) -> str:
    """Utility method to get the binhost path

    Args:
      build_target: build targets to get the binhost of.
      private: Whether the target's binhost is private.
      key: The binhost key, e.g. POSTSUBMIT_BINHOST.

    Returns:
      Path of the binhost file.
    """
    path_request = binhost_pb.GetBinhostConfPathRequest(
        build_target=build_target, private=private, key=key)
    path_response = \
        self.m.cros_build_api.BinhostService.GetBinhostConfPath(
            path_request, infra_step=True)
    binhost_path = self.m.path.abs_to_path(path_response.conf_path)
    return binhost_path

  def _upload(self, root, paths, uri, acls):
    """Upload the paths within root to the GS URI.

    This function symlinks all paths within the root directory to a temporary
    directory and then runs `gsutil rsync` to upload them. We use rsync because
    the uploads run in parallel and because it dedupes the prebuilts.

    Args:
      root (Path): The root directory.
      paths (List[str]): File paths (relative to root) to be uploaded.
      uri: The Google Storage URI to upload the paths to. Their path at the URI
          will match their path relative to the root. E.g., foo/bar.tbz2 will be
          uploaded to <uri>/foo/bar.tbz2.
      acls: (List[AclArg]): acls to apply to the uploaded prebuilts, will be
          empty if these prebuilts are public.
    """
    with self.m.step.nest('upload prebuilt blobs to GS'):
      sync_root = self.m.path.mkdtemp(prefix='prebuilts')
      symlink_tree = self.m.file.symlink_tree(sync_root)
      for relative_path in paths:
        local_path = root.join(relative_path)
        sync_path = symlink_tree.root.join(relative_path)
        symlink_tree.register_link(local_path, sync_path)
      symlink_tree.create_links('link files to upload')
      self.m.gsutil(['rsync', '-r', symlink_tree.root, uri],
                    parallel_upload=True, multithreaded=True)
      cmd = ['acl', 'ch', '-r']
      self._add_acls(acls, cmd)
      cmd.append(uri)
      self.m.gsutil(cmd, multithreaded=True)

  def _add_acls(self, acls, cmd):
    """Adds the acl arguments as arguments to command.

    Args:
      acls: (List[AclArg]): acls to convert to single acl string.
      cmd: (List[str]): list of arguments for gsutil invocation.
    """
    for acl in acls:
      cmd.append(acl.arg)
      cmd.append(acl.value)

  def _get_acls(self, private: bool,
                target: BuildTarget) -> List[binhost_pb.AclArgsResponse.AclArg]:
    """Returns private or public acls.

    Args:
      private: Whether or not the target prebuilts are private.
      target: The build target to get acls for.

    Returns:
      acls: A list of acls to use when interacting with Google
      storage.

    Raises:
      ValueError: If there are no acls for a private build target.
    """
    if not private:
      return [binhost_pb.AclArgsResponse.AclArg(arg='-u', value='AllUsers:R')]
    acls = self.m.cros_build_api.BinhostService.GetPrivatePrebuiltAclArgs(
        binhost_pb.AclArgsRequest(build_target=target), infra_step=True,
        name='read gs acls').args
    if not acls:
      raise ValueError('Private prebuilts uploads must have ACLs')
    return acls

  def upload_target_prebuilts(self, target, sysroot, chroot, profile, kind,
                              gs_bucket, private=True):
    """Upload binary prebuilts for the build target to Google Storage.

    Determines what to upload, uploads it, and points Portage to the upload URI.
    This step works entirely within the workspace checkout.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      chroot (chromiumos.common.Chroot): Chroot to work with.
      profile (chromiumos.Profile): The Profile, or None.
      kind (BuilderConfig.Id.Type): Kind of prebuilts to upload.
      gs_bucket (str): Google storage bucket to upload prebuilts to.
      private (bool): Whether or not the target prebuilts are private.
    """
    binhost_key = self._binhost_key(kind)
    with self.m.step.nest('upload prebuilts') as pres:
      # Set up the ACLs.
      acls = self._get_acls(private, target)

      upload_uri = self._prebuilts_uri(target, kind, gs_bucket)
      package_index_files = self._get_binhosts(target, chroot, private)
      upload_root, upload_paths = self._prepare_binhost_uploads(
          sysroot, chroot, upload_uri, package_index_files)
      self._upload(upload_root, upload_paths, upload_uri, acls)
      step = self.m.step('set properties', cmd=None)
      step.presentation.properties['prebuilts_private'] = private
      step.presentation.properties['prebuilts_uri'] = upload_uri

      if self.m.cros_source.is_source_dirty:
        pres.step_text = 'source dirty, skipping upload commit and metadata'
        return

      # Only buildbucket launched builds with the default profile should commit
      # BINHOST.conf updates.  Which can be explicitly disabled with the feature
      # flag.

      overlay_commit = (
          self.m.buildbucket.build.id and self._commit_overlay_binhost and
          self._profile_or_default(profile) == self._profile_or_default(None))

      if overlay_commit:
        # On CQ, we must not update binhost at this timing, since the final
        # result of entire CQ is not uncertain yet (i.e. other builder(s) in CQ
        # may fail).
        if BuilderConfig.Id.Type.Name(kind) == 'CQ':
          raise ValueError('CQ should not set the binhost.')

        with self.m.step.nest('update binhost conf file'):
          self.set_binhosts([(target, upload_uri)], private, binhost_key)

      # Default to `base` profile when it is not explicitly specified.
      profile = self._profile_or_default(profile)
      if self._enable_snapshot_prebuilts:
        self._upload_metadata(target, profile, kind, gs_bucket, acls,
                              upload_uri)

      # Upload binhost metadata to the `binhost_lookup_service`.
      self._publish_binhost_metadata(target, profile, upload_uri, gs_bucket,
                                     True, private)

  def upload_devinstall_prebuilts(self, target, sysroot, chroot, gs_bucket):
    """Upload binary devinstall prebuilts for build target to Google Storage.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      chroot (chromiumos.common.Chroot): Chroot to work with.
      kind (BuilderConfig.Id.Type): Kind of prebuilts to upload.
    """
    with self.m.step.nest('upload devinstall prebuilts') as presentation:
      if not gs_bucket:
        presentation.step_text = 'no bucket specified, skipping'
        return
      # First, set up the ACLs. dev_install prebuilts should always be public.
      acls = self._get_acls(False, target)

      # Next, craft the uri where these prebuilts will end up, so it can be
      # passed to the build-api to live in the metadata.
      upload_uri = self._devinstall_prebuilts_uri(
          target, gs_bucket, self.m.cros_infra_config.is_staging)

      # Next, hit the build API to get the devinstall prebuilts copied to a
      # directory.
      upload_root, upload_paths = self._prepare_devinstall_binhost_uploads(
          sysroot, upload_uri, chroot)

      # Finally, upload the prebuilts in the path up to gs.
      self._upload(upload_root, upload_paths, upload_uri, acls)

  def upload_chrome_prebuilts(self, target: BuildTarget, sysroot: Sysroot,
                              chroot: Chroot, profile: Optional[Profile],
                              kind: BuilderConfig.Id.Type, gs_bucket: str,
                              private: bool) -> None:
    """Upload Chrome binary prebuilts for the build target to Google Storage.

    Args:
      target: The build target to upload prebuilts for.
      sysroot: The sysroot whose prebuilts are being uploaded.
      chroot: Chroot to work with.
      profile: The Profile, or None.
      kind: Kind of prebuilts to upload.
      gs_bucket: Google storage bucket to upload prebuilts to.
      private: Whether or not the target prebuilts are private.

    Raises:
      ValueError: If a gs bucket was not specified.
    """
    with self.m.step.nest('upload chrome prebuilts'):
      if not gs_bucket:
        raise ValueError('A gs bucket was not specified for the upload.')

      # Set up the ACLs.
      acls = self._get_acls(private, target)

      # Get the upload targets from the build API.
      upload_uri = self._prebuilts_uri(target, kind, gs_bucket, profile)
      upload_root, upload_paths = self._prepare_chrome_binhost_uploads(
          sysroot, chroot, upload_uri)

      # Upload the prebuilts in the path to gs.
      self._upload(upload_root, upload_paths, upload_uri, acls)

      step = self.m.step('set properties', cmd=None)
      step.presentation.properties['prebuilts_private'] = private
      step.presentation.properties['prebuilts_uri'] = upload_uri

  def upload_host_prebuilts(self, target: BuildTarget, chroot: Chroot,
                            kind: BuilderConfig.Id.Type, gs_bucket: str,
                            profile: Optional[Profile] = None) -> None:
    """Upload host binary prebuilts to Google Storage.

    Args:
      target: The build target to upload prebuilts for.
      chroot: Chroot to work with.
      kind: Kind of prebuilts to upload.
      gs_bucket: Google storage bucket to upload prebuilts to.
      profile: The build target profile, or None.

    Raises:
      StepFailure: If a gs bucket was not specified.
    """
    with self.m.step.nest('upload host prebuilts'):
      if not gs_bucket:
        raise recipe_api.StepFailure(
            'A gs bucket was not specified for the upload.')

      # Set up the ACLs. Host prebuilts should always be public.
      acls = ['-a', 'public-read']

      # Determine the upload uri and file paths.
      upload_dest = self._get_host_prebuilts_dest(target, kind, self._build_id)
      host_prebuilts_dir = f'{chroot.path}/var/lib/portage/pkgs'

      # Upload the prebuilts to gs.
      self.m.gsutil.upload(host_prebuilts_dir, gs_bucket, upload_dest,
                           args=acls + ['-r'], multithreaded=True)

      # Update binhosts used by commiting BINHOST.conf changes. Only update
      # for the default profile.
      commit_overlay_binhost = self._profile_or_default(
          profile) == self._profile_or_default(None)
      if commit_overlay_binhost:
        upload_uri = f'gs://{gs_bucket}/{upload_dest}'
        binhost_key = self._binhost_key(kind)
        with self.m.step.nest('update binhost conf file'):
          self.set_binhosts([(target, upload_uri)], private=False,
                            key=binhost_key)

        step = self.m.step('set properties', cmd=None)
        step.presentation.properties['host_prebuilts_uri'] = upload_uri
