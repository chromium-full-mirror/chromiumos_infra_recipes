# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.util.util import exponential_retry
import datetime
import os
import re

DUMMY_IMAGE = 'cos-rc-85-13310-1015-0'
GCE_PREFIX = 'gce-tests'
GCE_TEST_BUCKET = 'images-in-test'
RAW_IMAGE_NAME = 'disk.raw'
TEST_IMAGE_NAME = 'chromiumos_test_image.bin'
GCE_CACHE_BUCKET = 'chromeos-bot-cache'
GCE_BUILD_PROJECT = 'chromeos-bot'
SSD_ZONES = ['us-central1-b', 'us-east1-d']

_SWARMING_HOST_REGEXP = (r'^chromeos-'
                         r'\w*-'
                         r'(?P<role>\w*)-'
                         r'(?P<zone>\w*-\w*-\w*)-'
                         r'(?P<suffix>.*)')

_DEFAULT_TEST_BOT_ID = 'chromeos-ci-infra-us-central1-b-x16-0-nvcj'


class GcloudApi(recipe_api.RecipeApi):
  """A module to interact with Google Cloud."""

  def __init__(self, *args, **kwargs):
    """Initialize GcloudApi."""
    super(GcloudApi, self).__init__(*args, **kwargs)
    self._cleanup_gce_stack = [[]]
    self._cleanup_mounted_stack = [[]]
    self._attached_disks = {}
    self._branch = None
    self._dev_ref = 'a'
    self._disk = None
    self._snapshot_suffix = None
    self._version_file = None
    self._zone = None
    self._infra_host = None
    self._overlay_branch_file = 'overlay_branch.txt'
    self._cache_mounted = False

  def initialize(self):
    self._infra_host = (
        _DEFAULT_TEST_BOT_ID
        if self._test_data.enabled else self.m.swarming.bot_id)

  @property
  def infra_host(self):
    if self._test_data.enabled and self._test_data.get('infra_host', None):
      return self._test_data.get('infra_host')
    return self._infra_host

  @property
  def snapshot_builder_mount_path(self):
    """Returns a Path to the base mount directory for cache builder."""
    return self.m.path['cleanup'].join('snapshot')

  @property
  def snapshot_mount_path(self):
    """The path to mount the snapshot disks.

    This is the path that the disks created from image will be mounted.
    """
    return '/snapshot_mounts'

  @property
  def snapshot_version_path(self):
    """The path to the local version file.

    This is the path to the local version file that contains the image
    version that was used to create the local named cache.
    """
    return self.m.path['cache'].join('infra_versions')

  @property
  def snapshot_suffix(self):
    return self._snapshot_suffix

  @property
  def host_zone(self):
    return self._zone

  @property
  def gce_disk(self):
    return self._disk

  @property
  def branch(self):
    return self._branch

  @property
  def snapshot_version_file(self):
    return self._version_file

  @property
  def gce_name_limit(self):
    return 63

  @property
  def gce_disk_blkid(self):
    return self._dev_ref

  def _is_rfc1035_compliant(self, branch):
    RFC_PATTERN = '^[a-z]([-a-z0-9]*[a-z0-9])?$'
    if not re.match(RFC_PATTERN, branch):
      return False
    if len(branch) > 63:
      return False
    return True

  def _scrub_special_characters(self, branch):
    """Removes special characters from branch names.
    Args:
      branch(str): Branch name to scrub for characters.

    Returns:
      String containing scrubbed branch name.
    """
    return re.sub('[^a-zA-Z0-9]+', '-', branch).lower()

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

  def list_all_instances(self):
    """Pulls a list of all disks that exist."""
    list_cmd = [
        'gcloud',
        'compute',
        'instances',
        'list',
        '--format',
        'json(name)',
    ]
    output = self.m.easy.stdout_json_step(
        'get a list of all instances', list_cmd,
        test_stdout=self.test_api.instances_data, infra_step=True)
    return [instance['name'] for instance in output]

  def lookup_device_id(self, disk_name):
    """Look up the device id in /dev/disk/by-id by name.

    Args:
      disk_name (str): The name associated with the attached device.
    Returns:
      Returns a dict map of device name to device id.
    """
    disk_dir = '/dev/disk/by-id'
    disk_device_map = {}
    disks = os.listdir(disk_dir)
    for disk in disks:
      device_id = os.path.basename(
          os.path.realpath(os.path.join(disk_dir, disk)))
      if disk.startswith('google-'):
        disk = disk[len(
            'google-'):]  # pragma: nocover, not expected to match in test.
      disk_device_map[disk] = device_id
    if self._test_data.enabled:
      disk_device_map['chromiumos'] = 'sdz'
    return disk_device_map.get(disk_name, None)

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
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
      # To ensure that the bot doesn't end in a weird state, detach
      # the disk before attaching since it should already be mounted.
      if not self.disk_attached(disk_name=name):
        self.m.step('attach disk', [
            'gcloud', 'compute', 'instances', 'attach-disk', instance,
            '--disk={}'.format(disk), '--device-name={}'.format(name),
            '--zone={}'.format(zone), '--quiet'
        ], infra_step=True)
        self._dev_ref = self.lookup_device_id(disk_name=name)
      self._attached_disks[name] = '/dev/{}'.format(self._dev_ref)
      self._add_cleanup_attached_disk(disk, instance, zone)

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

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
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
          '--disk={}'.format(disk), '--zone={}'.format(zone), '--quiet'
      ], infra_step=True)
    self._remove_cleanup_attached_disk(disk, instance, zone)

  def create_disk_from_snapshot(self, disk, zone, snapshot, disk_type=None):
    """Create a GCE disk from supplied snapshot.

    Create a GCE disk from a provided snapshot name.

    Args:
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create disk (e.g. us-central1-b).
      snapshot(str): Snapshot version use to create the disk.
      disk_type(str): Type of GCE disk to create.
    """
    cmd = [
        'gcloud', 'compute', 'disks', 'create', disk, '--zone={}'.format(zone),
        '--source-snapshot={}'.format(snapshot), '--quiet'
    ]
    if disk_type:
      cmd.extend(['--type={}'.format(disk_type)])
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create disk from snapshot', cmd, infra_step=True)

  def create_disk_from_image(self, disk, zone, image, disk_type=None):
    """Create a GCE disk from supplied image.

    Create a GCE disk from a provided snapshot name.

    Args:
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create disk (e.g. us-central1-b).
      image(str): Image version use to create the disk.
      disk_type(str): Type of GCE disk to create.
    """
    cmd = [
        'gcloud', 'compute', 'disks', 'create', disk, '--zone={}'.format(zone),
        '--image-project={}'.format(GCE_BUILD_PROJECT),
        '--image={}'.format(image), '--quiet'
    ]
    if disk_type:
      cmd.extend(['--type={}'.format(disk_type)])
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create disk from image', cmd, infra_step=True)

  def delete_disk(self, disk, zone):
    """Delete a GCE disk.

    Permanently delete a GCE disk from the project.

    Args:
      disk(str): Google Cloud disk name.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete disk', [
          'gcloud', 'compute', 'disks', 'delete', disk,
          '--zone={}'.format(zone), '--quiet'
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
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      if recipe_mount:
        recipe_mount_path = self.snapshot_builder_mount_path.join(name)
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

  def update_fstab(self, mount_path, name):
    """Mount an attached disk to host.

    As a disk is mounted, the disk is then added to the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      mount_path(str): Directory to mount the disk.
      name (str): An alphanumeric name for the mount, used for display.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      uuid_cmd = [
          'sudo', 'blkid', '-s', 'UUID', '-o', 'value',
          self._attached_disks[name]
      ]
      uuid = self.m.easy.stdout_step(
          'determine UUID', uuid_cmd,
          test_stdout='860a9e6a-f624-4f86-a00d-33a5cede3430').rstrip()
      self.m.step(
          'update fstab for %s' % self._attached_disks[name],
          ['sudo', 'tee', '-a', '/etc/fstab'], stdin=self.m.raw_io.input_text(
              'UUID={} {} ext4 discard,defaults,noatime,nofail 0 2'.format(
                  uuid, mount_path)), infra_step=True)

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
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

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def snapshot_exists(self, snapshot):
    """Check whether a snapshot exists.

    Args:
      snapshot(str): Name of the snapshot to check.

    Returns:
      Bool of whether the snapshot exists or not.
    """
    list_cmd = [
        'gcloud', 'compute', 'snapshots', 'list', '--format', 'json(name)',
        '--filter', 'name={}'.format(snapshot)
    ]
    output = self.m.easy.stdout_json_step(
        'check whether snapshot exists: {}'.format(snapshot), list_cmd,
        test_stdout=self.test_api.snapshot_exists_data, infra_step=True)
    for snap in output:
      if snapshot == snap['name']:
        return True
    return False

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def image_exists(self, image):
    """Check whether a image exists.

    Args:
      image(str): Name of the snapshot to check.

    Returns:
      Bool of whether the snapshot exists or not.
    """
    list_cmd = [
        'gcloud', 'compute', 'images', 'list', '--format', 'json(name)',
        '--filter', 'name={}'.format(image)
    ]
    output = self.m.easy.stdout_json_step(
        'check whether image exists: {}'.format(image), list_cmd,
        test_stdout=self.test_api.image_exists_data, infra_step=True)
    for img in output:
      if image == img['name']:
        return True
    return False

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def disk_exists(self, disk, zone):
    """Check whether a disk exists.

    Args:
      disk(str): Name of the disk to check.
      zone(str): GCE zone in which the disk exists.

    Returns:
      Bool of whether the disk exists or not.
    """
    list_cmd = [
        'gcloud', 'compute', 'disks', 'describe', disk,
        '--zone={}'.format(zone), '--format', 'json(name)'
    ]
    output = {}
    try:
      output = self.m.easy.stdout_json_step(
          'check whether disk exists: {}'.format(disk), list_cmd,
          test_stdout=self.test_api.disk_exists_data(disk=disk),
          infra_step=True)
    except self.m.step.StepFailure:
      self.m.step.active_result.presentation.status = 'SUCCESS'
    if disk == output.get('name', ''):
      return True
    return False

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def list_all_disks(self):
    """Pulls a list of all disks that exist.

    Returns:
      A dictionary containing disk name and zone.
    """
    list_cmd = [
        'gcloud',
        'compute',
        'disks',
        'list',
        '--filter',
        'name~chromeos-*',
        '--format',
        'json(name,zone)',
    ]
    output = self.m.easy.stdout_json_step(
        'get a list of all disks', list_cmd,
        test_stdout=self.test_api.disk_list_data, infra_step=True)
    disks = {}
    for gce_disk in output:
      disks[gce_disk['name']] = gce_disk['zone'].rsplit('/', 1)[1]
    return disks

  def disk_attached(self, disk_name):
    """Check whether a disk is attached to an instance.

    Args:
      disk_name(str): Disk name to match for device id.

    Returns:
      Bool of whether the disk is attached or not.
    """
    self._dev_ref = self.lookup_device_id(disk_name=disk_name)
    return bool(self._dev_ref)

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def create_image_from_disk(self, disk, image_name, zone):
    """Create an image from specified disk.

    Args:
      disk(str): Google Cloud disk name.
      image_name(str): The name to give the image.
      zone(str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create image from disk', [
          'gcloud', 'compute', 'images', 'create', image_name,
          '--source-disk={}'.format(disk), '--source-disk-zone={}'.format(zone)
      ], infra_step=True)

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
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
          test_stdout=self.test_api.snapshot_list_data, infra_step=True)
      for snap in snap_list:
        snapshot_name = snap['name']
        if protected_snapshots:
          if snapshot_name in protected_snapshots:
            continue
        if snapshot_name not in snapshot_list:
          snapshot_list.append(snapshot_name)
      del cmd[:]
    return snapshot_list

  def get_expired_images(self, retention_days, prefixes, protected_images=None):
    """Calculate the list of snapshots that have expired.

    Args:
      retention_days(int): Number of days to retain.
      prefixes(list|str): List of prefixes to filter.
      protected_images(list|str): List of images to preserve.
    """
    lookback_date = (
        self.m.time.utcnow() -
        datetime.timedelta(days=retention_days)).strftime("%Y-%m-%d")
    list_cmd = ['gcloud', 'compute', 'images', 'list', '--format', 'json']
    image_list = []
    cmd = []
    for prefix in prefixes:
      cmd.extend(list_cmd)
      cmd.extend([
          '--filter',
          'creationTimestamp<{} AND name~{}-.*'.format(lookback_date, prefix)
      ])
      images = self.m.easy.stdout_json_step(
          'list images with filter {}'.format(prefix), cmd,
          test_stdout=self.test_api.images_list_data, infra_step=True)
      for image in images:
        image_name = image['name']
        if protected_images:
          if image_name in protected_images:
            continue
        if image_name not in image_list:
          image_list.append(image_name)
      del cmd[:]
    return image_list

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def delete_images(self, images):
    """Delete the list of provided images from GCE.

    Args:
      images(list|str): A list of image names.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      for image in images:
        self.m.step('delete image {}'.format(image),
                    ['gcloud', 'compute', 'images', 'delete', image, '--quiet'],
                    infra_step=True)

  def determine_disks_to_delete(self, disks, instances):
    """Determines the list of orphaned disks to delete.

    Args:
      disks(dict): List of all GCE disks and zone
      instances(list|str): List of all GCE instances.

    Returns:
      Dictionary containing disk name and zone to delete.
    """
    disks_to_delete = {}
    for disk, zone in disks.items():
      # Naming standards shown in _SWARMING_HOST_REGEXP
      # mean that a standard disk is nine nodes long, anything
      # longer means the disk is a cache disk.
      if len(disk.split('-')) > 9:
        if disk.rsplit('-', 1)[0] not in instances:
          disks_to_delete[disk] = zone
    return disks_to_delete

  def _determine_disk_suffix(self, cache, branch):
    """Determine the name of the disk to create.

    Args:
      cache(str): Name of the cache disk to create.
      branch(str): Git branch.
    Returns:
      A string formatted disk suffix.
    """
    disk_suffix = ''
    if cache == 'chromiumos':
      disk_suffix = 'cros'
    elif cache == 'chrome':
      disk_suffix = 'cr'
    elif cache == 'chromeosSDK':
      disk_suffix = 'sdk'
    if 'release' in branch:
      disk_suffix = '{}{}'.format(disk_suffix, branch.split('-')[1]).lower()
    if 'stabilize' in branch:
      disk_suffix = '{}{}'.format(disk_suffix, 'stabilize')
    return disk_suffix

  def check_for_disk_mount(self, mount_path, mock_mount=False):
    """Check whether there is a disk mounted on given path.

    Args:
      mount_path (str): System path on which the disk is mounted.
      mock_mount (bool): Testing flag to mock a disk being mounted.

    Returns:
      Bool indicating whether there is a disk mounted on the path.
    """
    with self.m.step.nest(
        'determine whether cache is mounted and can be reused') as pres:
      if os.path.ismount(mount_path) or mock_mount:
        pres.logs['{}'.format(mount_path)] = 'is a mounted disk'
        return True
    return False

  def _swarming_information(self):
    """Set Swarming variables based on hostname."""
    with self.m.step.nest('get swarming hostname'):
      m = re.search(_SWARMING_HOST_REGEXP, self.infra_host)
      if not m:
        raise self.m.step.StepFailure(
            'failed to get zone from swarming host: {}'.format(self.infra_host))
      self._zone = m.group('zone')

  def setup_cache_disk(self, cache_name, branch='main', disk_type='pd-standard',
                       recipe_mount=False):
    """Create disk from snapshot, reuse if still attached.

    Check if disk is attached, otherwise grab the matching snapshot, create,
    attach, and mount the source disk.

    Args:
      cache_name(str): Name of the cache file to use.
      branch(str): Git branch.
      disk_type(str): Type of GCE disk to create, defaults to standard
        persistent disk.
      recipe_mount(bool): Whether mount needs to be in the path to use within
        a recipe.
    """
    if not self._zone or not self.infra_host:
      self._swarming_information()
    self.set_gce_project(GCE_BUILD_PROJECT)
    self._branch = branch
    is_staging = self.m.cros_infra_config.is_staging
    recovery_snapshot = 'initial-{}-source-snapshot'.format(cache_name)
    if not self._is_rfc1035_compliant(branch):
      self._branch = self._scrub_special_characters(self._branch)
    if self._branch == 'main' or recipe_mount:
      mount_path = cache_name
    else:
      mount_path = '{}-{}'.format(cache_name, self._branch)
    suffix = self._determine_disk_suffix(cache=cache_name, branch=branch)
    self._snapshot_suffix = str(self.m.time.ms_since_epoch())[0:8]
    self._version_file = '{}-{}-cache-snapshot-version.txt'.format(
        cache_name, self._branch)
    if is_staging:
      self._version_file = '{}-{}'.format('staging', self._version_file)
    recipe_mount_path = '{}/{}'.format(self.snapshot_mount_path, mount_path)
    self._cache_mounted = self.check_for_disk_mount(
        mount_path=recipe_mount_path)
    if not self._cache_mounted:
      with self.m.step.nest('setup source cache disk'):
        self._disk = '{}-{}'.format(self.infra_host, suffix)
        self._disk = self._disk[:self.gce_name_limit] if len(
            self._disk) > self.gce_name_limit else self._disk
        local_version = None
        local_version_path = self.snapshot_version_path.join(self._version_file)
        if self.m.path.exists(local_version_path):
          local_version = self.m.file.read_text(
              'read local image version', local_version_path,
              test_data='test-cache-snapshot-123')
        with self.m.step.nest('retrieve image version from storage'):
          try:
            remote_version = self.m.gsutil.cat(
                'gs://{}/{}'.format(GCE_CACHE_BUCKET, self._version_file),
                infra_step=True, stdout=self.m.raw_io.output()).stdout.strip()
          except self.m.step.StepFailure:
            with self.m.step.nest(
                'unable to find version file in GS bucket') as pres:
              # This is intended behavior if a new cache builder is added.
              # Rather than fail, default to an initial snapshot.
              pres.logs['version file not found'] = self._version_file
              remote_version = recovery_snapshot

        # TODO(b/202913239): Temporary fix due to bad image name
        remote_version = remote_version.replace("chromeos", "chromiumos")

        with self.m.step.nest('create disk from snapshot image'):
          snapshot = remote_version
          if local_version and self.image_exists(image=local_version):
            snapshot = local_version
          self.m.easy.set_properties_step(snapshot_version=snapshot)
          disk_exists = self.disk_exists(disk=self._disk, zone=self._zone)
          if disk_exists and recipe_mount:
            self.delete_disk(disk=self._disk, zone=self._zone)
            disk_exists = False
          if not disk_exists:
            # Create the disk but in the event of a stockout of SSD, catch the
            # exception and create a standard spinning disk.
            try:
              self.create_disk_from_image(disk=self._disk, zone=self._zone,
                                          image=snapshot, disk_type=disk_type)
            except self.m.step.StepFailure:
              self.create_disk_from_image(disk=self._disk, zone=self._zone,
                                          image=snapshot,
                                          disk_type='pd-standard')
          if not local_version and self.m.path.exists(
              self.m.path['cache'].join(cache_name).join('upperdir')):
            self.m.overlayfs.cleanup_overlay_directories(cache_name=cache_name)
          self.attach_disk(name=mount_path, instance=self.infra_host,
                           disk=self._disk, zone=self._zone)
          self.mount_disk(name=mount_path, mount_path=mount_path,
                          recipe_mount=recipe_mount)
          if not recipe_mount:
            self.update_fstab(mount_path=recipe_mount_path, name=mount_path)
            self.m.file.write_text(
                'write overlayfs branch file',
                self.snapshot_version_path.join(self._overlay_branch_file),
                self._branch)
            self.set_disk_autodelete(instance=self.infra_host, disk=self._disk,
                                     zone=self._zone)
          self.m.file.write_text('write version file', local_version_path,
                                 snapshot)
    if not recipe_mount:
      with self.m.step.nest('determine whether to reset overlayfs directories'):
        overlayfs_branch = 'main'
        try:
          overlayfs_branch = self.m.file.read_text(
              'read overlayfs branch',
              self.snapshot_version_path.join(self._overlay_branch_file),
              test_data='main')
        except self.m.step.StepFailure:
          self.m.step.active_result.presentation.status = 'SUCCESS'
          with self.m.step.nest(
              'branch not set for overlay, defaulting') as pres:
            # This is intended behavior if a new cache builder is added.
            # Rather than fail, default to an initial snapshot.
            pres.logs['overlay branch not found'] = overlayfs_branch
        if overlayfs_branch != self._branch:
          self.m.overlayfs.cleanup_overlay_directories(cache_name=cache_name)
    return recipe_mount_path

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
