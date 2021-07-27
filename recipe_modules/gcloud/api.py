# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
import contextlib
import datetime
import os

DUMMY_IMAGE = 'cos-rc-85-13310-1015-0'
GCE_PREFIX = 'gce-tests'
GCE_TEST_BUCKET = 'images-in-test'
RAW_IMAGE_NAME = 'disk.raw'
TEST_IMAGE_NAME = 'chromiumos_test_image.bin'


class GcloudApi(recipe_api.RecipeApi):
  """A module to interact with Google Cloud."""

  def __init__(self, *args, **kwargs):
    """Initialize GcloudApi."""
    super(GcloudApi, self).__init__(*args, **kwargs)
    self._cleanup_gce_stack = [[]]
    self._cleanup_mounted_stack = [[]]
    self._attached_disks = {}
    self._dev_ref = 'a'

  @property
  def _base_mount_path(self):
    """Returns a Path to the base mount directory for this module."""
    return self.m.path['cleanup'].join('snapshot')

  @property
  def snapshot_mount_path(self):
    """The path to mount the snapshot disks.

    This is the path that the disks created from snapshots will be mounted.
    """
    return '/snapshot_mounts'

  def set_gce_project(self, project):
    """Set the default project for gcloud command.
    Args:
      project(str): Google Cloud project name.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('set gcloud project',
                  ['gcloud', 'config', 'set', 'project', project])

  def auth_list(self, step_name=None):
    """Print out the auth creds currently on the bot.

    Args:
      step_name(str): Name of the step.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step(step_name or 'gcloud auth', ['gcloud', 'auth', 'list'])

  def prep_image(self, source_bucket, source_path, uniq_id):
    """Prepare the image to be used for testing.

    Args:
      source_bucket(str): Source GS bucket to download from.
      source_path(str): Path in GS to the build artifacts.
      uniq_id(int): ID to differentiate the image. Usually
          buildbucket_id of the build that generated the image.

    Returns: Path to the image tar file.
    """
    with self.m.step.nest('prepare image'):
      image_archive_dir = self.m.path.mkdtemp(prefix='image-archive')
      test_image_zip = image_archive_dir.join('image.zip')
      test_image_dir = image_archive_dir.join('image')
      test_image_path = str(test_image_dir.join(TEST_IMAGE_NAME))
      raw_image_path = str(test_image_dir.join(RAW_IMAGE_NAME))
      self.m.gsutil.download(source_bucket,
                             os.path.join(source_path,
                                          'image.zip'), test_image_zip,
                             name='download image bundle from GS')
      self.m.archive.extract('unzip image bundle', test_image_zip,
                             test_image_dir, include_files=[TEST_IMAGE_NAME])
      # Rename image and tar it up.
      self.m.file.move('Rename image to disk.raw', test_image_path,
                       raw_image_path)
      tar_file = '{}.tar.gz'.format(uniq_id)
      tar_path = str(test_image_dir.join(tar_file))
      with self.m.context(cwd=test_image_dir):
        self.m.step(
            'tar image',
            ['tar', '--format=oldgnu', '-Sczf', tar_file, RAW_IMAGE_NAME])
      return tar_path

  def create_image(self, tar_path, target, uniq_id):
    """Create an image in the GCE project.

    Args:
      tar_path(str): Path to the requisite image tar_file.
      target(str): Target being tested. (Ex:betty-arc-r)
      uniq_id(int): ID to differentiate the image. Usually
        buildbucket_id of the build that generated the image.

    Returns: A string name of the image.
    """
    with self.m.step.nest('create image'):
      tar_file = '{}.tar.gz'.format(uniq_id)
      self.m.gsutil.upload(tar_path, GCE_TEST_BUCKET,
                           '{}/{}'.format(target, tar_file))
      with self.m.context(env={'VIRTUAL_ENV': '1'}):
        image_name = '{}-{}'.format(target, uniq_id)
        self.m.step('gce create image', [
            'gcloud',
            'compute',
            'images',
            'create',
            image_name,
            '--source-uri=gs://{}/{}/{}'.format(GCE_TEST_BUCKET, target,
                                                tar_file),
        ])
        return image_name

  def delete_image(self, image_name):
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete image', [
          'gcloud',
          'compute',
          'images',
          'delete',
          image_name,
          '--quiet',
      ])

  def create_instance(self, image, project, machine, zone, network=None,
                      subnet=None):
    """Create an instance in the GCE project.

    Args:
      image(str): GCE image to use for the instance.
      project(str): Google Cloud project name.
      machine(str): GCE machine type
      zone(str): GCE zone to create instance (e.g. us-central1-b).
      network(str): Network name to use.
      subnet(str): Network subnet on which to create instance.

    Returns: A string name of the instance.
    """
    extra_args = []
    if network:
      extra_args.append('--network={}'.format(network))
    if subnet:
      extra_args.append('--subnet={}'.format(subnet))
    gcloud_cmd = [
        'gcloud', 'compute', 'instances', 'create', image,
        '--image={}'.format(image), '--project={}'.format(project),
        '--machine-type={}'.format(machine), '--no-scopes', '--no-address',
        '--zone={}'.format(zone)
    ]
    gcloud_cmd.extend(extra_args)
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create instance', gcloud_cmd)

  def delete_instance(self, instance, project, zone):
    """Delete a GCE instance.

    Args:
      instance(str): GCE instance to be deleted.
      project(str): Google Cloud project name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete instance', [
          'gcloud', 'compute', 'instances', 'delete', instance, '--quiet',
          '--zone={}'.format(zone), '--project={}'.format(project)
      ])

  def attach_disk(self, name, instance, disk, zone):
    """Attach a disk to a GCE instance.

    As a disk is attached, the disk is then added to the stack
    that is used by the context manager to detach as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      instance(str): GCE instance on which disk will be attached.
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('attach disk', [
          'gcloud',
          'compute',
          'instances',
          'attach-disk',
          instance,
          '--disk={}'.format(disk),
          '--zone={}'.format(zone),
      ], infra_step=True)
      # Increment the device reference; /dev/sda is root device.
      self._dev_ref = chr(ord(self._dev_ref) + 1)
      self._attached_disks[name] = '/dev/sd{}'.format(self._dev_ref)
      self._add_cleanup_attached_disk(disk, instance, zone)
      self.set_disk_autodelete(instance=instance, disk=disk, zone=zone)

  def sync_disk_cache(self, name):
    """Force a local disk cache sync before snapshotting.

    Args:
      name (str): Disk name to use to lookup the mount location.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      path_to_sync = self._attached_disks[name]
      self.m.step('sync disk', [
          'sudo',
          'sync',
          path_to_sync,
      ], infra_step=True)

  def detach_disk(self, instance, disk, zone):
    """Detach a disk to a GCE instance.

    As a disk is detached, the disk is then removed from the stack
    that is used by the context manager to detach as the task ends.

    Args:
      instance(str): GCE instance disk is attached.
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('detach disk', [
          'gcloud', 'compute', 'instances', 'detach-disk', instance,
          '--disk={}'.format(disk), '--zone={}'.format(zone)
      ], infra_step=True)
    self._remove_cleanup_attached_disk(disk, instance, zone)
    self._dev_ref = chr(ord(self._dev_ref) - 1)

  def create_disk(self, disk, zone, snapshot, disk_type=None):
    """Create a GCE disk.

    Create a GCE disk from a provided snapshot name.

    Args:
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create disk (e.g. us-central1-b).
      snapshot(str): Snapshot version use to create the disk.
      disk_type(str): Type of GCE disk to create.
    """
    cmd = [
        'gcloud', 'compute', 'disks', 'create', disk, '--zone={}'.format(zone),
        '--source-snapshot={}'.format(snapshot)
    ]
    if disk_type:
      cmd.extend(['--type={}'.format(disk_type)])
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create disk from snapshot', cmd, infra_step=True)

  def delete_disk(self, disk, zone):
    """Delete a GCE disk.

    Permanently delete a GCE disk from the project.

    Args:
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete disk', [
          'gcloud', 'compute', 'disks', 'delete', disk, '--zone={}'.format(zone)
      ], infra_step=True)

  def mount_disk(self, name, mount_path, recipe_mount=False):
    """Mount an attached disk to host.

    As a disk is mounted, the disk is then added to the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      mount_path(str): Directory to mount the disk.
      recipe_mount(bool): Whether mount needs to be in the path to use within
                        a recipe.

    Returns: Path to the mounted disk
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      if recipe_mount:
        recipe_mount_path = self._base_mount_path.join(mount_path)
        self.m.file.ensure_directory('create mount path', recipe_mount_path)
      else:
        recipe_mount_path = '{}/{}'.format(self.snapshot_mount_path, mount_path)
        # Ensure the mountpath exists.
        mount_dir_cmd = ['mkdir', '-p', recipe_mount_path]
        self.m.step('ensure mount directory exists', mount_dir_cmd,
                    infra_step=True)
      self.m.step('mount disk %s' % name, [
          'sudo', 'mount', '-o', 'discard,defaults', self._attached_disks[name],
          recipe_mount_path
      ], infra_step=True)
      self._add_cleanup_mounted_disk(name, recipe_mount_path)
      return recipe_mount_path

  def unmount_disk(self, name, mount_path):
    """Unmount an attached disk to host.

    As a disk is unmounted, the disk is then removed from the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      mount_path(str): Directory to mount the disk.
    """
    unmount_script = self.repo_resource('recipe_scripts/umount_path.sh')
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      cmd = str(unmount_script)
      self.m.step('unmount disk %s' % name, [cmd, mount_path], infra_step=True)
      self._remove_cleanup_mounted_disk(name, mount_path)

  def snapshot_disk(self, disk, snapshot_name, zone):
    """Snapshot an attached disk on a GCE instance.

    Args:
      disk(str): Google Cloud disk name.
      snapshot_name(str): The name to give the snapshot.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('snapshot disk', [
          'gcloud', 'compute', 'disks', 'snapshot', disk,
          '--snapshot-names={}'.format(snapshot_name), '--zone={}'.format(zone)
      ], infra_step=True)

  def delete_snapshots(self, snapshots):
    """Delete the list of provided snapshots from GCE.

    Args:
      snapshots(list|str): A list of snapshot names.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      for snapshot in snapshots:
        self.m.step(
            'delete snapshot {}'.format(snapshot),
            ['gcloud', 'compute', 'snapshots', 'delete', snapshot, '--quiet'],
            infra_step=True)

  def get_expired_snapshots(self, retention_days, prefixes,
                            protected_snapshots=None):
    """Calculate the list of snapshots that have expired.

    Args:
      retention_days(int): Number of days to retain.
      prefixes(list|str): List of prefixes to filter.
      protected_snapshots(list|str): List of snapshots to preserve.
    """
    lookback_date = (
        self.m.time.utcnow() -
        datetime.timedelta(days=retention_days)).strftime("%Y-%m-%d")
    list_cmd = ['gcloud', 'compute', 'snapshots', 'list', '--format', 'json']
    snapshot_list = []
    cmd = []
    for prefix in prefixes:
      cmd.extend(list_cmd)
      cmd.extend([
          '--filter',
          'creationTimestamp<{} AND name~{}-.*'.format(lookback_date, prefix)
      ])
      snap_list = self.m.easy.stdout_json_step(
          'list snapshots with filter {}'.format(prefix), cmd,
          test_stdout=lambda: self.test_api.snapshot_list_data(),
          infra_step=True)
      for snap in snap_list:
        snapshot_name = snap['name']
        if protected_snapshots:
          if snapshot_name in protected_snapshots:
            continue
        if snapshot_name not in snapshot_list:
          snapshot_list.append(snapshot_name)
      del cmd[:]
    return snapshot_list

  def set_disk_autodelete(self, instance, disk, zone):
    """Set a disk to autodelete when a GCE instance is deleted.

    GCE disks are not default to delete when the instance is
    deleted, thus to ensure cleanup we can flip the metadata
    to ensure the disks are deleted when the instance is removed.

    Args:
      instance(str): GCE instance on which disk is attached.
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('set disk to autodelete', [
          'gcloud',
          'compute',
          'instances',
          'set-disk-auto-delete',
          instance,
          '--auto-delete',
          '--disk={}'.format(disk),
          '--zone={}'.format(zone),
      ], infra_step=True)

  @contextlib.contextmanager
  def cleanup_gce_disks(self):
    """Wrap disk cleanup in a context handler to ensure they are handled.

    Upon exiting the context manager, each attached disk is then iterated
    through to unmount, detach, and delete the disk.
    """
    cleanup_gce_disks = []
    self._cleanup_gce_stack.append(cleanup_gce_disks)
    try:
      yield
    finally:
      if cleanup_gce_disks:
        with self.m.step.nest('clean up gce disk'):
          for disk, instance, zone in list(cleanup_gce_disks):
            self.detach_disk(instance, disk, zone)
            self.delete_disk(disk, zone)
      self._cleanup_gce_stack.pop()

  def _add_cleanup_attached_disk(self, disk, instance, zone):
    """Track attach disk for cleanup_attached_disks.

    Each attached disk is added to the stack to be detached by
    the context handler.
    """
    self._cleanup_gce_stack[-1].append((disk, instance, zone))

  def _remove_cleanup_attached_disk(self, disk, instance, zone):
    """Track detach disk for cleanup_attached_disks.

    As a disk is detached, the item is then removed from the stack
    to avoid attempting to detach at a later time.
    """
    item = (disk, instance, zone)
    for mounts in reversed(self._cleanup_gce_stack):
      if item in mounts:
        mounts.remove(item)
        break
    else:
      # Detach succeeded, but the requested disk was not found in the
      # cleanup stack so we assume we already detached it.
      self.m.step.active_result.presentation.step_text += (
          '<br/>[WARNING: gcloud delete disk bookkeeping error for %s]' % disk)

  @contextlib.contextmanager
  def cleanup_mounted_disks(self):
    """Wrap disk cleanup in a context handler to ensure they are unmounted.

    Upon exiting the context manager, each mounted disk is then iterated
    through and unmounted.
    """
    cleanup_mounted_disks = []
    self._cleanup_mounted_stack.append(cleanup_mounted_disks)
    try:
      yield
    finally:
      if cleanup_mounted_disks:
        with self.m.step.nest('clean up mounted compute disk'):
          for name, mount_path in list(cleanup_mounted_disks):
            self.unmount_disk(name, mount_path)
      self._cleanup_mounted_stack.pop()

  def _add_cleanup_mounted_disk(self, name, mount_path):
    """Track mounted disk for cleanup_mounted_disks.

    Each mounted disk is added to the stack to be removed by
    the context handler.
    """
    self._cleanup_mounted_stack[-1].append((name, mount_path))

  def _remove_cleanup_mounted_disk(self, name, mount_path):
    """Track unmounted disk for cleanup_mounted_disks.

    As a disk is unmounted, the item is then removed from the stack
    to avoid attempting to unmount at a later time.
    """
    item = (name, mount_path)
    for mounts in reversed(self._cleanup_mounted_stack):
      if item in mounts:
        mounts.remove(item)
        break
    else:
      # Unmount succeeded, but the requested disk was not found in the
      # cleanup stack so we assume we already unmounted it.
      self.m.step.active_result.presentation.step_text += (
          '<br/>[WARNING: gcloud unmount disk bookkeeping error for %s]' %
          mount_path)
