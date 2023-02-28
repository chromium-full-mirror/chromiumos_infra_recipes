# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS prebuilts to Google Storage."""

import os

from google.protobuf import json_format

from PB.chromite.api import binhost as binhost_pb
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageIndexInfo
from PB.chromiumos.common import Path
from PB.chromiumos.common import Profile
from recipe_engine import recipe_api

# The trailing / is for gsutil rsync.
METADATA_GS_DIR_TMPL = 'gs://{gs_bucket}/snapshot/{snapshot}/{target}/{profile}/'
METADATA_GS_FILE_TMPL = '{builder}-{build_id}-{kind}.json'


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

  def _prebuilts_uri(self, target, kind, gs_bucket):
    """Determine the GS URI to upload prebuilts.

    Args:
      target (BuildTarget): The build target.
      kind (BuilderConfig.Id.Type): The kind of prebuilts, e.g. POSTSUBMIT
      gs_bucket (str): Google storage bucket to upload prebuilts to.

    Returns:
      The full GS URI in which to upload prebuilts.
    """
    label = BuilderConfig.Id.Type.Name(kind).lower()
    version = self.m.cros_version.version
    return 'gs://%s/board/%s/%s-%s-%s/packages' % (
        gs_bucket, target.name, label, version, self._build_id)

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

  def _get_snapshot_package_index_info(self, snapshots, build_target, profile,
                                       gs_bucket, test_data_dict=None):
    """Get prebuilts metadata for snapshots.

    Returns PackageIndexInfo entries for the newest available prebuilts for each
    of the given build_targets.

    Args:
      snapshots (list[str]): List of snapshot git SHA strings, newest first.
      build_target (BuildTarget): The BuildTarget to fetch.
      profile (chromiumos.Profile): Profile to fetch.
      gs_bucket (str): Google storage bucket where the prebuilts live.
      test_data_dict (dict): Dictionary of test data:
        test_data_dict[snapshot][target_name][file_name] = PackageIndexInfo

    Returns:
      (list[PackageIndexInfo]) The metadata for CreateSysrootService.
    """
    test_data_dict = test_data_dict or {}
    test_snapshot_num = 5555
    download_root = self.m.path.mkdtemp(prefix='metadata')
    target = build_target.name
    profile = self._profile_or_default(profile)

    def _get_test_data(data, snapshot, target, profile):
      return data.get(snapshot, {}).get(target, {}).get(profile, {})

    ret = []
    snapshots_found = 0

    for snapshot in snapshots:
      with self.m.step.nest('{}/{}/{}'.format(snapshot, target,
                                              profile.name)) as presentation:
        download_dir = download_root.join(snapshot, target, profile.name)
        self.m.file.ensure_directory('ensure directory', download_dir)
        uri = METADATA_GS_DIR_TMPL.format(gs_bucket=gs_bucket,
                                          snapshot=snapshot, target=target,
                                          profile=profile.name)
        self.m.gsutil(['rsync', uri, download_dir], multithreaded=True)

        listdir_test_data = []
        if self._test_data.enabled:
          for fname in _get_test_data(test_data_dict, snapshot, target,
                                      profile.name):
            self.m.path.mock_add_paths(download_dir.join(fname))
            listdir_test_data.append(fname)

        files = self.m.file.listdir('listdir', download_dir,
                                    test_data=listdir_test_data)
        presentation.step_text = ('found %d file%s' %
                                  (len(files), 's' if len(files) != 1 else ''))
        if files:
          snapshots_found += 1
          presentation.logs['files found'] = [
              str(self.m.path.relpath(x, download_dir)) for x in files
          ]
          for meta in files:
            name = self.m.path.basename(meta)
            test_data = _get_test_data(
                test_data_dict, snapshot, target, profile.name).get(
                    name,
                    PackageIndexInfo(
                        snapshot_sha=snapshot,
                        snapshot_number=test_snapshot_num,
                        build_target=BuildTarget(name=target),
                        location='gs://{}/testdata/{}'.format(gs_bucket, name)))
            ret.append(
                self.m.file.read_proto('read {}'.format(name), meta,
                                       PackageIndexInfo, 'JSONPB',
                                       test_proto=test_data))
      test_snapshot_num -= 1
      if snapshots_found >= self._send_snapshot_prebuilts:
        break

    return ret

  def get_package_index_info(self, gs_bucket, snapshot=None, build_target=None,
                             profile=None, count=None, test_data_dict=None,
                             name=None):
    """Return the PackageIndexInfo for this build.

    Args:
      gs_bucket (str): Google storage bucket where the prebuilts live.
      snapshot (GitilesCommit): The snapshot for this build, or None.
      build_target (BuildTarget): BuildTarget for the build, or None.
      profile (chromiumos.Profile): Profile for the build, or None.
      count (int): Number of snapshots to check, or None.
      test_data_dict (dict): Dictionary of test data:
        test_data_dict[snapshot][target_name][file_name] = PackageIndexInfo
      name (str): Name for the step, or None.

    Returns:
      (list[PackageIndexInfo]) The metadata for CreateSysrootService.
    """
    if not self._send_snapshot_prebuilts:
      return []

    # Assume 2 snapshot per hour, we want 7 days worth of them.  We will walk
    # back in time until we find $chromeos_prebuilts.send_snapshot_prebuilts
    # snapshots that have any prebuilts.  (To account for the possibility of
    # multiple builders with the same profile and different use flags.
    count = count or 7 * 24 * 2
    snapshot = snapshot or self.m.cros_infra_config.gitiles_commit
    build_target = build_target or self.m.cros_infra_config.get_build_target()
    profile = self._profile_or_default(profile)

    with self.m.step.nest(name or 'find prebuilts'):
      shas = self.m.cros_source.fetch_snapshot_shas(count=count)
      test_data_dict = (
          test_data_dict or self.test_api.generate_snapshot_test_data_dict(
              shas, build_target, profile, gs_bucket))

      return self._get_snapshot_package_index_info(
          shas, build_target, profile, gs_bucket, test_data_dict=test_data_dict)

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
      profile = self._profile_or_default(profile)

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
      # TODO(b/271075149): Remove this hack after submitting crrev.com/c/4273070.
      if name.upper() == "CQ":
        return binhost_pb.BinhostKey.Value('POSTSUBMIT_BINHOST')

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

  def _get_binhosts(self, target, private):
    """Download binhost files from google storage.

    Download binhost files from google storage and returns PackageInfo files
    specifying their location.

    Args:
      target (BuildTarget): Build target getting binhosts for.
      private (bool): whether to include private binhosts.

    Returns:
      List[PackageInfo]: Package info files to deduplicate the prebuilt list.
    """
    with self.m.step.nest('get binhosts'):
      request = binhost_pb.BinhostGetRequest(build_target=target,
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

  def _prepare_binhost_uploads(self, sysroot, uri, package_index_files):
    """Determine which prebuilt archives should be uploaded to the binhost.

    Args:
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      uri (str): URI where prebuilts will be uploaded.
      package_index_files (List[PackageIndex]): package index files to
          deduplicate the prebuilt list.

    Returns:
      tuple(Path, List[str]): Path to directory containing uploads and
          a list of uploadable string paths relative to that directory.
    """
    with self.m.step.nest('prepare binhost uploads'):
      request = binhost_pb.PrepareBinhostUploadsRequest(
          sysroot=sysroot, uri=uri, package_index_files=package_index_files)
      response = self.m.cros_build_api.BinhostService.PrepareBinhostUploads(
          request, infra_step=True)
      upload_root = self.m.path.abs_to_path(response.uploads_dir)
      upload_paths = [ut.path for ut in response.upload_targets]
      return upload_root, upload_paths

  def _prepare_devinstall_binhost_uploads(self, sysroot, uri):
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
          uri=uri)
      response = self.m.cros_build_api.BinhostService.PrepareDevInstallBinhostUploads(
          request, infra_step=True)
      upload_paths = [ut.path for ut in response.upload_targets]
      return upload_root, upload_paths

  def _set_binhost(self, target, private, key, uri, push_retries):
    """Set the target's Portage binhost to point to the given URI.

    This function updates a conf file within the target's overlay, commits the
    change, and pushes it.

    Args:
      target (BuildTarget): Build target to update the binhost for.
      private (bool): Whether the target's binhost is private.
      key (BinhostKey): The binhost key, e.g. POSTSUBMIT_BINHOST.
      uri (str): The new binhost URI.
      push_retries (int): Number of times to retry pushing the changes.
    """
    with self.m.step.nest('update binhost conf file'):
      # In order to avoid any merge conflicts we first pull the latest changes
      # from remote, update the conf flie locally, and then push the
      # changes remotely.
      path_request = binhost_pb.GetBinhostConfPathRequest(
          build_target=target, private=private, key=key)
      path_response = self.m.cros_build_api.BinhostService.GetBinhostConfPath(
          path_request, infra_step=True)
      binhost_path = self.m.path.abs_to_path(path_response.conf_path)
      projects = self.m.repo.project_infos(
          projects=[self.m.path.dirname(binhost_path)])
      assert len(projects) == 1, '%s must belong to 1 project' % binhost_path
      project = projects[0]
      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project.path)):
        branch = project.branch
        if branch:
          # The unit tests needs the ebuilds to be the same version we build them at.
          # so after we pull the latest and commit our changes, we checkout the
          # the commit from which we started. Here we are saving the current commit
          # so we can checkout again after we push our updates.
          current_commit = self.m.git.head_commit()

          # Staging doesn't have ACLs to push conf files to the real branch.
          # Instead, use a branch with the last component named 'staging'
          if self._use_staging_branch:
            branch_parts = branch.split('/')
            branch_parts[-1] = 'staging'
            branch = '/'.join(branch_parts)

          # There are instances when, in between fetching from remote and then
          # commiting our changes, a different builder can commit its changes.
          # This can cause merging issues(see ex:http://shortn/_WtgjVa2ayK).
          # We can retry few times to avoid it.
          for attempt in range(push_retries + 1):
            self.m.git.fetch_ref(project.remote, branch)
            self.m.git.checkout('FETCH_HEAD', force=True)
            request = binhost_pb.SetBinhostRequest(
                build_target=target, private=private, key=key, uri=uri,
                max_uris=self._max_binhost_uris)
            self.m.cros_build_api.BinhostService.SetBinhost(
                request, infra_step=True)
            binhost_data = self.m.file.read_text('read binhost conf',
                                                 binhost_path)
            lines = [
                'Set %s=%s.' % (binhost_pb.BinhostKey.Name(key), uri),
                'go/bbid/%s' % self._build_id
            ]

            try:
              self.m.git_txn.update_ref_write_file(project.remote,
                                                   '\n'.join(lines),
                                                   binhost_path, binhost_data,
                                                   automerge=True, ref=branch)
              self.m.git.checkout(current_commit)
              return
            except recipe_api.StepFailure as ex:
              if attempt == push_retries:
                raise ex

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

  def upload_target_prebuilts(self, target, sysroot, profile, kind, gs_bucket,
                              private=True):
    """Upload binary prebuilts for the build target to Google Storage.

    Determines what to upload, uploads it, and points Portage to the upload URI.
    This step works entirely within the workspace checkout.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      profile (chromiumos.Profile): The Profile, or None.
      kind (BuilderConfig.Id.Type): Kind of prebuilts to upload.
      gs_bucket (str): Google storage bucket to upload prebuilts to.
      private (bool): Whether or not the target prebuilts are private.
    """
    binhost_key = self._binhost_key(kind)
    with self.m.step.nest('upload prebuilts') as pres:
      if private:
        acls = self.m.cros_build_api.BinhostService.GetPrivatePrebuiltAclArgs(
            binhost_pb.AclArgsRequest(build_target=target), infra_step=True,
            name='read gs acls').args
        assert len(acls) > 0, 'private prebuilts uploads must have ACLs'
      else:
        # Mark them public.
        acls = [binhost_pb.AclArgsResponse.AclArg(arg='-u', value='AllUsers:R')]

      upload_uri = self._prebuilts_uri(target, kind, gs_bucket)
      package_index_files = self._get_binhosts(target, private)
      upload_root, upload_paths = self._prepare_binhost_uploads(
          sysroot, upload_uri, package_index_files)
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

        self._set_binhost(target, private, binhost_key, upload_uri,
                          push_retries=3)

      if self._enable_snapshot_prebuilts:
        self._upload_metadata(target, profile, kind, gs_bucket, acls,
                              upload_uri)

  def upload_devinstall_prebuilts(self, target, sysroot, gs_bucket):
    """Upload binary devinstall prebuilts for build target to Google Storage.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      sysroot (Sysroot): The sysroot whose prebuilts are being uploaded.
      kind (BuilderConfig.Id.Type): Kind of prebuilts to upload.
    """
    with self.m.step.nest('upload devinstall prebuilts') as presentation:
      if not gs_bucket:
        presentation.step_text = 'no bucket specified, skipping'
        return
      # First, set up the ACLs. dev_install prebuilts should always be public.
      acls = [binhost_pb.AclArgsResponse.AclArg(arg='-u', value='AllUsers:R')]

      # Next, craft the uri where these prebuilts will end up, so it can be
      # passed to the build-api to live in the metadata.
      upload_uri = self._devinstall_prebuilts_uri(
          target, gs_bucket, self.m.cros_infra_config.is_staging)

      # Next, hit the build API to get the devinstall prebuilts copied to a
      # directory.
      upload_root, upload_paths = self._prepare_devinstall_binhost_uploads(
          sysroot, upload_uri)

      # Finally, upload the prebuilts in the path up to gs.
      self._upload(upload_root, upload_paths, upload_uri, acls)
