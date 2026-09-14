# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for gcloud commands."""

import contextlib
import datetime
import json
import os
import re
from typing import List
from typing import Optional

from recipe_engine.recipe_api import StepFailure
from recipe_engine import recipe_api

from PB.recipe_modules.chromeos.gcloud.gcloud import (SourceCacheAction)
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

GCE_CACHE_BUCKET = 'chromeos-bot-cache'
DEFAULT_GCE_PROJECT = 'chromeos-bot'
DEFAULT_SOURCE_CACHE_GCE_PROJECT = 'chromeos-release-bot'

_SWARMING_HOST_REGEXP = (r'^(chromeos|chromiumos)-'
                         r'\w*-'
                         r'(?P<role>\w*)-'
                         r'(?P<zone>\w*-\w*-\w*)-'
                         r'(?P<suffix>.*)')

_DEFAULT_TEST_BOT_ID = 'chromeos-ci-infra-us-central1-b-x16-0-nvcj'

# TODO(b/216558719): Consider removing this when gcloud issue is resolved.
_RE_DISK_SIZE = re.compile("New disk size '(?P<first>[0-9]+)' GiB must be "
                           "larger than existing size '(?P<second>[0-9]+)' "
                           'GiB.')

# Sometimes asking to create a disk results in the disk existing, even when
# we've recently asked cloud about the status of the resource and received a
# 404. See: b/141640651.
_RE_DISK_EXISTS = re.compile('The resource .+ already exists')

RECOVERY_IMAGE_TEMPLATE = 'initial-{}-source-snapshot'
RECOVERY_IMAGE_FALLBACK_TEMPLATE = '{}-fallback'

ATTACH_DISK_TIMEOUT_SECONDS = 180
SET_DISK_AUTODELETE_TIMEOUT_SECONDS = 180


class GcloudApi(recipe_api.RecipeApi):
  """A module to interact with Google Cloud."""

  def __init__(self, properties, *args, **kwargs):
    """Initialize GcloudApi."""
    super().__init__(*args, **kwargs)
    self._attached_disks = {}
    self._branch = None
    self._cache_mounted = False
    self._cleanup_gce_stack = [[]]
    self._cleanup_mounted_stack = [[]]
    self._dev_ref = 'a'
    self._disk = None
    self._gce_project = (properties.gce_project or DEFAULT_GCE_PROJECT)
    self._source_cache_gce_project = (
        properties.source_cache_gce_project or DEFAULT_SOURCE_CACHE_GCE_PROJECT)
    self._infra_host = None
    self._overlay_branch_file = 'overlay_branch.txt'
    self._snapshot_suffix = None
    self._version_file = None
    self._zone = None
    self._short_name = None
    self._disk_exists_count = 0

    # Cache properties.
    self._mounted_snapshot = None
    self._cache_action = (
        properties.source_cache_action or
        SourceCacheAction.MOUNT_LATEST_CACHE_IMAGE)
    self._specific_image_to_mount = properties.specific_image_to_mount


  def initialize(self):
    self._infra_host = (
        _DEFAULT_TEST_BOT_ID
        if self._test_data.enabled else self.m.swarming.bot_id)
    not_latest_sync = self.cache_action is not SourceCacheAction.MOUNT_LATEST_CACHE_IMAGE
    self._dont_reuse_mounted_cache = not_latest_sync or 'chromeos.gcloud.dont_reuse_cache' in self.m.cros_infra_config.experiments

  @property
  def cache_action(self):
    return self._cache_action

  @cache_action.setter
  def cache_action(self, val):
    self._cache_action = val

  @property
  def infra_host(self):
    if self._test_data.enabled and self._test_data.get('infra_host', None):
      return self._test_data.get('infra_host')
    return self._infra_host

  @property
  def snapshot_builder_mount_path(self):
    """Returns a Path to the base mount directory for cache builder."""
    return self.m.path.cleanup_dir / 'snapshot'

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
    return self.m.path.cache_dir / 'infra_versions'

  @property
  def snapshot_suffix(self):
    return self._snapshot_suffix

  @property
  def host_zone(self):
    return self._zone

  @property
  def gce_project(self):
    return self._gce_project

  @property
  def source_cache_gce_project(self):
    return self._source_cache_gce_project

  @property
  def gce_disk(self):
    if self._test_data.get('is_mount'):
      return '{}-{}'.format(self.infra_host, self._short_name)
    return self._disk

  @property
  def branch(self):
    return self._branch

  @property
  def snapshot_version_file(self):
    return self._version_file

  @property
  def disk_short_name(self):
    return self._short_name

  @property
  def gce_name_limit(self):
    return 63

  @property
  def gce_disk_blkid(self):
    return self._dev_ref

  @property
  def mounted_snapshot(self):
    return self._mounted_snapshot

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
      branch (str): Branch name to scrub for characters.

    Returns:
      String containing scrubbed branch name.
    """
    return re.sub('[^a-zA-Z0-9]+', '-', branch).lower()

  def set_gce_project(self, project):
    """Set the default project for gcloud command.
    Args:
      project (str): Google Cloud project name.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('set gcloud project',
                  ['gcloud', 'config', 'set', 'project', project])

  def auth_list(self, step_name=None):
    """Print out the auth creds currently on the bot.

    Args:
      step_name (str): Name of the step.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step(step_name or 'gcloud auth', ['gcloud', 'auth', 'list'])

  def create_image(self, image_name, source_uri=None, licenses=None):
    """Creates an image in the GCE project.

    Args:
      image_name (str): Name of the image.
      source_uri (str, optional): Sets the `--source-uri` flag if the image
        source is a tarball. See gcloud docs for detail.
      licenses (list[str], optional): List of image licenses to apply.
    """
    # source_uri is made optional to leave room for other image sources in the
    # future (--source-disk, --source-image, etc.), although it's currently the
    # only supported type and effectively required.
    # Once other sources are supported we should check here if exactly one of
    # the arguments is set.
    if source_uri is None:
      raise ValueError('source_uri not set')

    cmd = ['gcloud', 'compute', 'images', 'create', image_name]
    if source_uri is not None:
      cmd.append('--source-uri={}'.format(source_uri))
    if licenses is not None:
      cmd.append('--licenses={}'.format(','.join(licenses)))

    with self.m.step.nest('create image'), \
        self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('gce create image', cmd, infra_step=True)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def delete_image(self, image_name):
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete image', [
          'gcloud',
          'compute',
          'images',
          'delete',
          image_name,
          '--quiet',
      ], infra_step=True)

  def create_instance(self, image, project, machine, zone, network=None,
                      subnet=None, external_ip=False):
    """Create an instance in the GCE project.

    Args:
      image (str): GCE image to use for the instance.
      project (str): Google Cloud project name.
      machine (str): GCE machine type
      zone (str): GCE zone to create instance (e.g. us-central1-b).
      network (str): Network name to use.
      subnet (str): Network subnet on which to create instance.
      external_ip (bool): Enables external IP address.

    Returns:
      Tuple[str, str, str|None]: (name, ip_addr, ext_ip_addr) of the instance.
    """
    extra_args = []
    ext_ip_addr = None
    if network:
      extra_args.append('--network={}'.format(network))
    if subnet:
      extra_args.append('--subnet={}'.format(subnet))
    if not external_ip:
      extra_args.append('--no-address')
    gcloud_cmd = [
        'gcloud',
        'compute',
        'instances',
        'create',
        image,
        '--image={}'.format(image),
        '--project={}'.format(project),
        '--machine-type={}'.format(machine),
        '--no-scopes',
        '--zone={}'.format(zone),
        '--format=json',
    ]
    gcloud_cmd.extend(extra_args)
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      output = self.m.easy.stdout_json_step(
          'create instance', gcloud_cmd,
          test_stdout=self.test_api.instance_data, infra_step=True)
      if external_ip:
        ext_ip_addr = output[0]['networkInterfaces'][0]['accessConfigs'][0][
            'natIP']
      return output[0]['name'], output[0]['networkInterfaces'][0][
          'networkIP'], ext_ip_addr

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def delete_instance(self, instance, project, zone):
    """Delete a GCE instance.

    Args:
      instance (str): GCE instance to be deleted.
      project (str): Google Cloud project name.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete instance', [
          'gcloud', 'compute', 'instances', 'delete', instance, '--quiet',
          '--zone={}'.format(zone), '--project={}'.format(project)
      ], infra_step=True)

  def list_all_instances(self):
    """Pulls a list of all instances that exist."""
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
      Returns the device id of the provided disk name, defaulting to None if no
      disk can be found.
    """
    with self.m.step.nest('look up device name to device id map') as pres:
      disk_dir = '/dev/disk/by-id'
      disk_device_map = {}

      if self._test_data.enabled:
        disk_device_map['cros'] = 'sdz'
        disk_device_map['crosr90'] = 'sdy'
        disk_device_map['crosstabilize'] = 'sdx'
        disk_device_map['test-disk'] = 'sdw'
        disk_device_map['cache_test1'] = 'sdv'
        disk_device_map['cache_test2'] = 'sdu'
        disk_device_map['cr'] = 'sdt'
        disk_device_map['internal-cros'] = 'sds'
      else:  # pragma: no cover
        disks = os.listdir(disk_dir)
        for disk in disks:
          device_id = os.path.basename(
              os.path.realpath(os.path.join(disk_dir, disk)))
          if disk.startswith('google-'):
            disk = disk[len('google-'):]
          disk_device_map[disk] = device_id

        # Emit the map as output.
        pres.logs['device_map'] = json.dumps(disk_device_map, indent=2)

    return disk_device_map.get(disk_name, None)

  def disk_attached_in_gce(self, instance, disk_name, zone):
    """Check whether a disk is attached to an instance according to GCE.

    Args:
      instance (str): GCE instance name.
      disk_name (str): Device name of the disk to check.
      zone (str): GCE zone of the instance.

    Returns:
      bool: True if GCE reports the disk as attached to the instance.
    """
    describe_cmd = [
        'gcloud',
        'compute',
        'instances',
        'describe',
        instance,
        '--zone={}'.format(zone),
        '--format=json(disks)',
    ]
    try:
      output = self.m.easy.stdout_json_step(
          'check GCE attached disks', describe_cmd,
          test_stdout={'disks': [{
              'deviceName': disk_name
          }]}, infra_step=True, timeout=60)
      disks = output.get('disks', []) if isinstance(output, dict) else []
      return any(d.get('deviceName') == disk_name for d in disks)
    except (recipe_api.StepFailure, recipe_api.InfraFailure):
      return False

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def attach_disk(self, name, instance, disk, zone, force_attach=False):
    """Attach a disk to a GCE instance.

    As a disk is attached, the disk is then added to the stack
    that is used by the context manager to detach as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      instance (str): GCE instance on which disk will be attached.
      disk (str): Google Cloud disk name.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
      force_attach (bool): If True, attach without checking local attachment.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      need_attach = True
      if not force_attach and self.disk_attached(disk_name=name):
        # /dev/disk/by-id node exists locally. Verify that the GCE control plane
        # also considers the disk attached to this instance, to guard against
        # stale/ghost SCSI device nodes from previous builds or aborted attaches.
        need_attach = not self.disk_attached_in_gce(instance=instance,
                                                    disk_name=name, zone=zone)

      if need_attach:
        self.m.step('attach disk', [
            'gcloud', 'compute', 'instances', 'attach-disk', instance,
            '--disk={}'.format(disk), '--device-name={}'.format(name),
            '--zone={}'.format(zone), '--quiet'
        ], infra_step=True, timeout=ATTACH_DISK_TIMEOUT_SECONDS)
        self._dev_ref = self.lookup_device_id(disk_name=name)
        # The gcloud command will fail silently if it does not attach
        # a disk. However, that disk will not appear in the device map.
        # Since this method is within an exponential retry block, in
        # such a case we fail and let it retry.
        if not self._dev_ref:
          raise recipe_api.StepFailure(
              'gcloud sdk failed to attach disk {}'.format(name))

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

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def detach_disk(self, instance, disk, zone):
    """Detach a disk to a GCE instance.

    As a disk is detached, the disk is then removed from the stack
    that is used by the context manager to detach as the task ends.

    Args:
      instance (str): GCE instance disk is attached.
      disk (str): Google Cloud disk name.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('detach disk', [
          'gcloud', 'compute', 'instances', 'detach-disk', instance,
          '--disk={}'.format(disk), '--zone={}'.format(zone), '--quiet'
      ], infra_step=True)
    self._remove_cleanup_attached_disk(disk, instance, zone)

  def _wrap_in_disk_exists_swallow(self, func):
    """Wraps the provided function in an exception handler that swallows.

    Swallows all errors of the type "the resource x already exists".

    Args:
      func (Function): Function to try to execute.
    """
    try:
      func()
    except self.m.step.StepFailure as e:
      disk_exists = (e.result.stderr and _RE_DISK_EXISTS.search(
          e.result.stderr)) or (e.result.stdout and _RE_DISK_EXISTS.search(
              e.result.stdout.decode('utf-8')))
      if not disk_exists:
        raise e
      self._disk_exists_count += 1
      self.m.easy.set_properties_step(
          disk_already_exists_count=self._disk_exists_count)

  def create_disk(self, disk, zone, image=None, disk_type=None, size=None):
    """Create a GCE disk.

    Create a GCE disk using the provided options.

    Args:
      disk (str): Google Cloud disk name.
      zone (str): GCE zone to create disk (e.g. us-central1-b).
      image (str): Image version use to create the disk. If none, will create a
                  blank disk.
      disk_type (str): Type of GCE disk to create.
      size (str): Size of disk in gcloud format (e.g. 100GB).

    Returns:
      The stdout of the gcloud command.
    """
    # Specify self.source_cache_gce_project which houses images.
    cmd = [
        'gcloud', 'compute', 'disks', 'create', disk, '--zone={}'.format(zone),
        '--image-project={}'.format(self.source_cache_gce_project), '--quiet'
    ]

    step_name = 'create empty disk'
    if image:
      cmd.extend(['--image={}'.format(image)])
      step_name = 'create disk from image'
    if disk_type:
      cmd.extend(['--type={}'.format(disk_type)])
    if size:
      cmd.extend(['--size={}'.format(size)])

    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      return self.m.easy.stdout_step(
          step_name, cmd, infra_step=True,
          stderr=self.m.raw_io.output_text(add_output_log=True))

  def delete_disk(self, disk, zone):
    """Delete a GCE disk.

    Permanently delete a GCE disk from the project.

    Args:
      disk (str): Google Cloud disk name.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete disk', [
          'gcloud', 'compute', 'disks', 'delete', disk,
          '--zone={}'.format(zone), '--quiet'
      ], infra_step=True)

  def mount_disk(self, name, mount_path, recipe_mount=False, chown=False):
    """Mount an attached disk to host.

    As a disk is mounted, the disk is then added to the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      mount_path (str): Directory to mount the disk.
      recipe_mount (bool): Whether mount needs to be in the path to use within
                        a recipe.
      chown (bool): Whether or not to chown the disk after mounting. This is
                    needed for newly created disks.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      if recipe_mount:
        recipe_mount_path = self.snapshot_builder_mount_path / mount_path
        self.m.file.ensure_directory('create mount path', recipe_mount_path)
      else:
        recipe_mount_path = '{}/{}'.format(self.snapshot_mount_path, mount_path)
        # Ensure the mountpath exists.
        mount_dir_cmd = ['mkdir', '-p', recipe_mount_path]
        self.m.step('ensure mount directory exists', mount_dir_cmd,
                    infra_step=True)

      # If we're trying to mount a disk that wasn't mounted by this invocation
      # try to look it up first from the systems disk-by-id inventory.
      if not name in self._attached_disks:
        self._dev_ref = self.lookup_device_id(disk_name=name)
        self._attached_disks[name] = '/dev/{}'.format(self._dev_ref)

      self.m.step('mount disk %s' % name, [
          'sudo', 'mount', '-t', 'ext4', '-o', 'discard,defaults',
          self._attached_disks[name], recipe_mount_path
      ], infra_step=True)
      if chown:
        # Since the disk was created and formatted with root, we need to make
        # certain chrome-bot has ownership over the disk.
        chown_cmd = [
            'sudo', 'chown', '-R', 'chrome-bot:chrome-bot', recipe_mount_path
        ]
        self.m.easy.stdout_step('chown the disk', chown_cmd, infra_step=True)
      self._add_cleanup_mounted_disk(name, recipe_mount_path)

  def unmount_disk(self, name, mount_path):
    """Unmount an attached disk to host.

    As a disk is unmounted, the disk is then removed from the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      name (str): An alphanumeric name for the mount, used for display.
      mount_path (str): Directory to mount the disk.
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
      mount_path (str): Directory to mount the disk.
      name (str): An alphanumeric name for the mount, used for display.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      uuid_cmd = [
          'sudo', 'blkid', '-s', 'UUID', '-o', 'value',
          self._attached_disks[name]
      ]
      uuid = self.m.easy.stdout_step(
          'determine UUID', uuid_cmd,
          test_stdout='860a9e6a-f624-4f86-a00d-33a5cede3430').decode(
              'utf-8').rstrip()
      self.m.step(
          'update fstab for %s' % self._attached_disks[name],
          ['sudo', 'tee', '-a', '/etc/fstab'], stdin=self.m.raw_io.input_text(
              'UUID={} {} ext4 discard,defaults,noatime,nofail 0 2'.format(
                  uuid, mount_path)), infra_step=True)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def set_disk_autodelete(self, instance, name, zone, disk=None):
    """Set a disk to autodelete when a GCE instance is deleted.

    GCE disks are not default to delete when the instance is
    deleted, thus to ensure cleanup we can flip the metadata
    to ensure the disks are deleted when the instance is removed.

    Args:
      instance (str): GCE instance on which disk is attached.
      name (str): Google Cloud disk name.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
      disk (str): Optional persistent disk name to re-attach if unattached.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      try:
        self.m.step('set disk to autodelete', [
            'gcloud',
            'compute',
            'instances',
            'set-disk-auto-delete',
            instance,
            '--auto-delete',
            '--device-name={}'.format(name),
            '--zone={}'.format(zone),
        ], infra_step=True, timeout=SET_DISK_AUTODELETE_TIMEOUT_SECONDS)
      except (recipe_api.StepFailure, recipe_api.InfraFailure) as e:
        # If GCE reports that the disk is not attached, attempt to reconcile by
        # re-attaching it and re-trying.
        if disk and not self.disk_attached_in_gce(instance, name, zone):
          if self.m.step.active_result:
            self.m.step.active_result.presentation.status = self.m.step.WARNING
          with self.m.step.nest('reconcile unattached disk in GCE') as pres:
            pres.step_text = 'Disk {} not attached in GCE; re-attaching'.format(
                name)
            self.attach_disk(name=name, instance=instance, disk=disk, zone=zone,
                             force_attach=True)
          self.m.step('set disk to autodelete (reconciled)', [
              'gcloud',
              'compute',
              'instances',
              'set-disk-auto-delete',
              instance,
              '--auto-delete',
              '--device-name={}'.format(name),
              '--zone={}'.format(zone),
          ], infra_step=True, timeout=SET_DISK_AUTODELETE_TIMEOUT_SECONDS)
        else:
          raise e

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def image_exists(self, image):
    """Check whether a image exists.

    Args:
      image (str): Name of the snapshot to check.

    Returns:
      Bool of whether the snapshot exists or not.
    """
    list_cmd = [
        'gcloud', 'compute', 'images', 'list', '--format', 'json(name)',
        '--filter', 'name={}'.format(image)
    ]
    # If we aren't in self.source_cache_gce_project, specify it because it houses images.
    if self._gce_project != self.source_cache_gce_project:
      list_cmd += ['--project', self.source_cache_gce_project]
    test_stdout = self.test_api.image_exists_data
    # If there is test data set for this call, pass that through. Otherwise, use
    # the default response from test_api.
    if self._test_data.enabled and 'set_image_exists_data' in self._test_data:
      test_stdout = self._test_data.get('set_image_exists_data')

    output = self.m.easy.stdout_json_step(
        'check whether image exists: {}'.format(image), list_cmd,
        test_stdout=test_stdout, infra_step=True)
    for img in output:
      if image == img['name']:
        return True
    return False

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def disk_exists(self, disk, zone):
    """Check whether a disk exists.

    Args:
      disk (str): Name of the disk to check.
      zone (str): GCE zone in which the disk exists.

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

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
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
      disk_name (str): Disk name to match for device id.

    Returns:
      Bool of whether the disk is attached or not.
    """
    self._dev_ref = self.lookup_device_id(disk_name=disk_name)
    return bool(self._dev_ref)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def resize_disk(self, disk, zone, size):
    """Resize the GCE disk above the default of 200GB.

    Args:
      disk (str): Google Cloud disk name.
      zone (str): GCE zone which the disk is located.
      size (str): New size of the disk in GB.
    """

    def _is_set_size(gcloud_str):
      """Check the stdout if the actual is same as requested size."""
      re_match = _RE_DISK_SIZE.search(gcloud_str)
      if re_match and re_match.group('first') and re_match.group('second'):
        if re_match.group('first') == re_match.group('second'):
          return True
      return False

    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      try:
        self.m.easy.stdout_step(
            'resize GCE disk', [
                'gcloud', 'compute', 'disks', 'resize', disk,
                '--size={}'.format(size), '--zone={}'.format(zone), '--quiet'
            ], infra_step=True,
            stderr=self.m.raw_io.output_text(add_output_log=True))
      except self.m.step.InfraFailure as e:
        # Check output that indicates we've actually succeded.
        if not _is_set_size(
            e.result.stdout.decode('utf-8')) and not _is_set_size(
                e.result.stderr):
          raise
        self.m.step.active_result.presentation.step_text = 'Disk was already correct size.'

      self.m.easy.stdout_step(
          'execute resize2fs on resized disk',
          ['sudo', 'resize2fs', '/dev/{}'.format(self._dev_ref)],
          test_stdout='The filesystem on /dev/{} is now 262143739 (4k) blocks long.'
          .format(self._dev_ref))

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def create_gcloud_image(self, step_name: str, image_name: str,
                          props: List[str]):
    """Create an image.

    Args:
      image_name: The name to give the image.
      props: Additional props to pass in to the create command.
      step_name: Step name to use.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      cmd = ['gcloud', 'compute', 'images', 'create', image_name] + props
      self._wrap_in_disk_exists_swallow(lambda: self.m.easy.stdout_step(
          step_name, cmd, infra_step=True, stderr=self.m.raw_io.output_text(
              add_output_log=True)))

  def create_image_from_disk(self, disk, image_name, zone):
    """Create an image from specified disk.

    Args:
      disk (str): Google Cloud disk name.
      image_name (str): The name to give the image.
      zone (str): GCE zone to create instance (e.g. us-central1-b).
    """
    self.create_gcloud_image(
        'create image from disk', image_name,
        ['--source-disk={}'.format(disk), '--source-disk-zone={}'.format(zone)])

  def create_image_from_image(self, image_name: str, existing_image: str):
    """Create an image from an existing image.

    Args:
      image_name: The name to give the image.
      existing_image: The name of the existing image.
    """
    self.create_gcloud_image('create image from image', image_name,
                             ['--source-image={}'.format(existing_image)])

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def get_expired_images(self, retention_days, prefixes, protected_images=None):
    """Calculate the list of images that have expired.

    Args:
      retention_days (int): Number of days to retain.
      prefixes (list|str): List of prefixes to filter.
      protected_images (list|str): List of images to preserve.
    """
    lookback_date = (
        self.m.time.utcnow() -
        datetime.timedelta(days=retention_days)).strftime('%Y-%m-%d')
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

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def delete_images(self, images):
    """Delete the list of provided images from GCE.

    Args:
      images (list|str): A list of image names.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      for image in images:
        self.m.step('delete image {}'.format(image),
                    ['gcloud', 'compute', 'images', 'delete', image, '--quiet'],
                    infra_step=True)

  def determine_disks_to_delete(self, disks, instances):
    """Determines the list of orphaned disks to delete.

    Args:
      disks (dict): List of all GCE disks and zone
      instances (list|str): List of all GCE instances.

    Returns:
      Dictionary containing disk name and zone to delete.
    """
    disks_to_delete = {}
    for disk, zone in disks.items():
      # Naming standards shown in _SWARMING_HOST_REGEXP
      # mean that a standard disk is nine nodes long, anything
      # longer means the disk is a cache disk.
      if len(disk.split('-')) > 9:
        if '-'.join(disk.split('-')[0:9]) not in instances:
          disks_to_delete[disk] = zone
    return disks_to_delete

  def _determine_disk_suffix(self, cache, branch):
    """Determine the name of the disk to create.

    Args:
      cache (str): Name of the cache disk to create.
      branch (str): Git branch.
    Returns:
      A string formatted disk suffix.
    """
    disk_suffix = ''
    if cache == 'chromiumos':
      disk_suffix = 'cros'
    elif cache == 'chromeos':
      disk_suffix = 'internal-cros'
    elif cache == 'chrome':
      disk_suffix = 'cr'
    elif cache == 'chromeosSDK':
      disk_suffix = 'sdk'
    if 'release' in branch:
      disk_suffix = '{}{}'.format(disk_suffix, branch.split('-')[1]).lower()
    if 'stabilize' in branch:
      disk_suffix = '{}{}'.format(disk_suffix, 'stabilize')
    return disk_suffix

  def check_for_disk_mount(self, mount_path):
    """Check whether there is a disk mounted on given path.

    Args:
      mount_path (str): System path on which the disk is mounted.

    Returns:
      Bool indicating whether there is a disk mounted on the path.
    """
    with self.m.step.nest(
        'determine whether cache is mounted and can be reused') as pres:
      is_mount = os.path.ismount(mount_path)
      if self._test_data.enabled:
        is_mount = self._test_data.get('is_mount', False)
      if is_mount:
        pres.logs['{}'.format(mount_path)] = 'is a mounted disk'
    return is_mount

  def _get_swarming_machine_type(self) -> str:
    """Read machine_type dimension from Swarming / Buildbucket if found."""
    bot_dims = getattr(self.m.buildbucket, 'swarming_bot_dimensions',
                       None) or []

    for dimension in bot_dims:
      if dimension.key == 'machine_type':
        return dimension.value

    return ''

  def get_default_disk_type(self) -> str:
    """Determine compatible disk type based on Swarming machine type dimension.

    Gen4 machine families (e.g. N4, N4D, C4, C4D) do not support traditional
    pd-ssd disks and require hyperdisk.

    Fall back to pd-ssd for other machine families (e.g. N1, N2, N2D, E2) or
    if machine type is not found.
    """
    machine_type = self._get_swarming_machine_type().lower()
    if machine_type.startswith(('n4-', 'n4d-', 'c4-', 'c4d-')):
      return 'hyperdisk-balanced'
    return 'pd-ssd'

  def _swarming_information(self):
    """Set Swarming variables based on hostname."""
    m = re.search(_SWARMING_HOST_REGEXP, self.infra_host)
    if not m:
      raise self.m.step.StepFailure(
          'failed to get zone from swarming host: {}'.format(self.infra_host))
    self._zone = m.group('zone')

  def _get_image_version(self, recovery_snapshot):
    """Based on the requested cache action, return the image version.

    Args:
      recovery_snapshot (str): Recovery image to fall back on.

    Returns:
      String of the image file to use, or None.
    """
    # If cache action is latest cache image, look that image up from the
    # version file.
    if self.cache_action is SourceCacheAction.MOUNT_LATEST_CACHE_IMAGE:
      with self.m.step.nest('retrieve image version from storage'):
        try:
          return self.m.gsutil.cat(
              'gs://{}/{}'.format(GCE_CACHE_BUCKET,
                                  self._version_file), infra_step=True,
              stdout=self.m.raw_io.output_text()).stdout.strip()
        except self.m.step.StepFailure:
          self.m.step.active_result.presentation.status = 'SUCCESS'
          with self.m.step.nest(
              'unable to find version file in GS bucket') as pres:
            # This is intended behavior if a new cache builder is added.
            # Rather than fail, default to an initial snapshot.
            pres.logs['version file not found'] = self._version_file
            return recovery_snapshot
    # If cache action is recovery image, use the provided snapshot image.
    elif self.cache_action is SourceCacheAction.MOUNT_RECOVERY_IMAGE:
      with self.m.step.nest(
          'retrieve initial snapshot image from storage') as pres:
        pres.logs['snapshot_image'] = recovery_snapshot
        return recovery_snapshot
    # If a specific image is provided, use that.
    elif self.cache_action is SourceCacheAction.MOUNT_SPECIFIC_IMAGE:
      with self.m.step.nest('retrieve specific image from storage') as pres:
        pres.logs['snapshot_image'] = self._specific_image_to_mount
        return self._specific_image_to_mount

    # Otherwise this is a no-cache flow, and thus the image doesn't matter.
    return None

  def _setup_empty_cache_disk(self, disk_type=None):
    """Set up a brand new disk for use as a cache disk.

    In contrast to _create_new_cache_disk below which uses the previous image
    (or the recovery image) as the basis for its checkout, this creates an empty
    disk and sets it up for a fresh sync from scratch. Note that this step does
    *not* do a repo init on the new disk, because the disk is not yet mounted.

    Args:
      disk_type (str): Type of GCE disk to create, defaults to machine-compatible
        disk type.
    """
    disk_type = disk_type or self.get_default_disk_type()
    # Check to see if a disk exists, and if so delete it.
    disk_exists = self.disk_exists(disk=self._disk, zone=self._zone)
    if disk_exists:
      if self.disk_attached(disk_name=self._short_name):
        self.detach_disk(instance=self.infra_host, disk=self._disk,
                         zone=self._zone)
      self.delete_disk(disk=self._disk, zone=self._zone)
    # Create an empty disk.
    try:
      # The cache image disks are of size 200GB. Gcloud defaults to 100GB
      # for SSDs, so specify a size of 200GB to match the cache disk.
      self._wrap_in_disk_exists_swallow(lambda: self.create_disk(
          disk=self._disk, zone=self._zone, disk_type=disk_type, size='200GB'))
    except self.m.step.StepFailure:
      self._wrap_in_disk_exists_swallow(lambda: self.create_disk(
          disk=self._disk, zone=self._zone, disk_type=disk_type, size='200GB'))
    # Attach disk.
    self.attach_disk(name=self._short_name, instance=self.infra_host,
                     disk=self._disk, zone=self._zone)

    # Format it.
    disk = '/dev/{}'.format(self.lookup_device_id(self._short_name))
    format_cmd = [
        'sudo', 'mkfs.ext4', '-m', '0', '-E',
        'lazy_itable_init=0,lazy_journal_init=0,discard', disk
    ]
    self.m.easy.stdout_step('format empty disk', format_cmd, infra_step=True)

  def _create_new_cache_disk(self, cache_name, disk_type, recipe_mount,
                             recovery_snapshot=None):
    """Create a new cache disk.

    New cache disk is based on snapshot image stored in Google Storage, or
    recovery snapshot.

    Args:
      cache_name (str): Name of the cache file to use.
      disk_type (str): Type of GCE disk to create, defaults to standard
        persistent disk.
      recipe_mount (bool): Whether mount needs to be in the path to use within
        a recipe.
      recovery_snapshot (str): Recovery snapshot to fall back to, defaults to
        `initial-{cache_name}-source-snapshot`.

    Returns:
      Str containing the name of the snapshot.
    """
    with self.m.step.nest('setup source cache disk'):
      self._disk = '{}-{}'.format(self.infra_host, self._short_name)
      self._disk = (self._disk[:self.gce_name_limit]
                    if len(self._disk) > self.gce_name_limit else
                    self._disk).rstrip('-')
      recovery_snapshot = (
          recovery_snapshot or RECOVERY_IMAGE_TEMPLATE.format(cache_name))
      remote_version = self._get_image_version(recovery_snapshot)

      if self.cache_action is SourceCacheAction.DONT_MOUNT_ANY_CACHE:
        with self.m.step.nest('create disk with empty checkout'):
          self._setup_empty_cache_disk(disk_type)
        return None

      with self.m.step.nest('create disk from snapshot image'):
        snapshot = remote_version
        # Notice here that we check for image existence (even in cases where
        # the config requests the latest image or a specific image) and if
        # said image does not exist, we fall back on the snapshot image.
        if not self.image_exists(image=snapshot):
          snapshot = recovery_snapshot
          # If the recovery image is in the process of being deleted, it could
          # not exist. In this case, fall back on the recovery B image.
          fallback_image = RECOVERY_IMAGE_FALLBACK_TEMPLATE.format(snapshot)
          if not self.image_exists(image=snapshot) and self.image_exists(
              image=fallback_image):
            snapshot = fallback_image
        self.m.easy.set_properties_step(snapshot_version=snapshot)
        disk_exists = self.disk_exists(disk=self._disk, zone=self._zone)
        if disk_exists and (recipe_mount or self._dont_reuse_mounted_cache):
          if disk_exists and self._dont_reuse_mounted_cache:
            with self.m.step.nest('discarding mounted cache') as pres:
              pres.text = 'skipping reuse of mounted cache'
          if self.disk_attached(disk_name=self._short_name):
            self.detach_disk(instance=self.infra_host, disk=self._disk,
                             zone=self._zone)
          self.delete_disk(disk=self._disk, zone=self._zone)
          disk_exists = False

        if not disk_exists:
          # Create the disk with retry, catching if the disk is perhaps already
          # in existence (false 404 from earlier check).
          try:
            self._wrap_in_disk_exists_swallow(lambda: self.create_disk(
                disk=self._disk, zone=self._zone, image=snapshot,
                disk_type=disk_type))
          except self.m.step.StepFailure:
            self._wrap_in_disk_exists_swallow(
                lambda: self.create_disk(disk=self._disk, zone=self._zone,
                                         image=snapshot, disk_type=disk_type))
        return snapshot or None

  def _setup_new_cache_mount_outside_path(self, recipe_mount_path):
    """Perform cache setup when mount is allowed to be outside the path.

    Args:
      recipe_mount_path (path): Location (in recipes) to mount attached disk.
    """
    self.update_fstab(mount_path=recipe_mount_path, name=self._short_name)
    self.m.file.write_text(
        'write overlayfs branch file',
        self.snapshot_version_path / self._overlay_branch_file, self._branch)
    try:
      self.set_disk_autodelete(instance=self.infra_host, name=self._short_name,
                               zone=self._zone, disk=self._disk)
    except (recipe_api.StepFailure, recipe_api.InfraFailure) as e:
      with self.m.step.nest('failed to set auto-delete') as pres:
        pres.status = self.m.step.WARNING
        pres.step_text = ('Failed to set auto-delete on disk {}: {}. '
                          'Continuing since disk is mounted and usable.'.format(
                              self._short_name, e))

  def _reset_overlayfs_if_needed(self, cache_name):
    """Reset overlayfs to named cache.

    Changing branches necessitates reseting overlayfs to the named cache
    because we expect the upper dir source code to change substantially
    from branch to branch.

    Args:
      cache_name (str): Name of the cache file to use.
    """
    with self.m.step.nest('determine whether to reset overlayfs directories'):
      overlayfs_branch = 'main'
      try:
        overlayfs_branch = self.m.file.read_text(
            'read overlayfs branch',
            self.snapshot_version_path / self._overlay_branch_file,
            test_data='main')
      except self.m.step.StepFailure:
        self.m.step.active_result.presentation.status = 'SUCCESS'
        with self.m.step.nest('branch not set for overlay, defaulting') as pres:
          # This is intended behavior if a new cache builder is added.
          # Rather than fail, default to an initial snapshot.
          pres.logs['overlay branch not found'] = overlayfs_branch
      if overlayfs_branch != self._branch:
        self.m.overlayfs.cleanup_overlay_directories(cache_name=cache_name)

  def _verify_cache_config(self):
    """Verifies that the config props for source cache are valid combos."""
    if (self._specific_image_to_mount and
        self.cache_action is not SourceCacheAction.MOUNT_SPECIFIC_IMAGE) or (
            self.cache_action is SourceCacheAction.MOUNT_SPECIFIC_IMAGE and
            not self._specific_image_to_mount):
      raise StepFailure(
          'specific_image_to_mount must be provided with cache action MOUNT_SPECIFIC_IMAGE'
      )

  def setup_cache_disk(self, cache_name, branch='main', disk_type=None,
                       disk_size=None, recipe_mount=False,
                       disallow_previously_mounted=False, mount_existing=False,
                       recovery_snapshot=None):
    """Create disk from snapshot, reuse if still attached.

    Check if disk is attached, otherwise grab the matching snapshot, create,
    attach, and mount the source disk.

    Args:
      cache_name (str): Name of the cache file to use.
      branch (str): Git branch.
      disk_type (str): Type of GCE disk to create, defaults to machine-compatible
        disk type ('hyperdisk-balanced' for gen4 otherwise 'pd-ssd').
      disk_size (str): Size of the disk to create in GB, defaults to image size.
      recipe_mount (bool): Whether mount needs to be in the path to use within
        a recipe.
      disallow_previously_mounted (bool): If set, this step will fail if the
        cache is already mounted.
      mount_existing (bool): If we find an existing cache, mount it immediately
        instead of relying on subsequent step.
      recovery_snapshot (str): Recovery snapshot to fall back to, defaults to
        `initial-{cache_name}-source-snapshot`.
    """
    # Verify source cache config.
    self._verify_cache_config()
    disk_type = disk_type or self.get_default_disk_type()
    # Set properties we need for cache disk setup.
    if not self._zone or not self.infra_host:
      self._swarming_information()
    self.set_gce_project(self._gce_project)
    self._branch = branch
    is_staging = self.m.cros_infra_config.is_staging
    if not self._is_rfc1035_compliant(branch):
      self._branch = self._scrub_special_characters(self._branch)
    if self._branch == 'main' or recipe_mount:
      mount_path = cache_name
    else:
      mount_path = '{}-{}'.format(cache_name, self._branch)
    self._short_name = self._determine_disk_suffix(cache=cache_name,
                                                   branch=branch)
    self._snapshot_suffix = str(self.m.time.ms_since_epoch())[0:8]
    self._version_file = '{}-{}-cache-snapshot-version.txt'.format(
        cache_name, self._branch)
    if is_staging:
      self._version_file = '{}-{}'.format('staging', self._version_file)
    recipe_mount_path = '{}/{}'.format(self.snapshot_mount_path, mount_path)
    with self.m.step.nest('source cache'):
      self._cache_mounted = self.check_for_disk_mount(
          mount_path=recipe_mount_path)
      if self._cache_mounted and disallow_previously_mounted:
        # In certain cases (namely, SourceCacheBuilder) we cannot tolerate re-using
        # a cache that was mounted on the bot during an earlier build.
        # b/222488162 for context.
        raise recipe_api.StepFailure(
            '`disallow_previously_mounted` is True and the cache was already mounted'
        )
      # No cache case. In the case of break-glass, we treat it as a no-reuse.
      if not self._cache_mounted or self._dont_reuse_mounted_cache:
        local_version_path = self.snapshot_version_path / self._version_file
        snapshot = self._create_new_cache_disk(
            cache_name, disk_type, recipe_mount,
            recovery_snapshot=recovery_snapshot)

        if self.cache_action is not SourceCacheAction.DONT_MOUNT_ANY_CACHE:
          self.attach_disk(name=self._short_name, instance=self.infra_host,
                           disk=self._disk, zone=self._zone)

      if not self._cache_mounted or self._dont_reuse_mounted_cache or mount_existing:
        self.mount_disk(
            name=self._short_name,
            mount_path=mount_path,
            recipe_mount=recipe_mount,
            # If the cache action is to not mount any cache, the disk will have
            # been newly created and formatted by root. In that case, we will
            # need to chown the mount point to ensure the bot user has proper
            # permissions to repo init later on.
            chown=self.cache_action is SourceCacheAction.DONT_MOUNT_ANY_CACHE)
        if not recipe_mount:
          self._setup_new_cache_mount_outside_path(recipe_mount_path)

      if not self._cache_mounted or self._dont_reuse_mounted_cache:
        if disk_size:
          self.resize_disk(disk=self._disk, zone=self._zone, size=disk_size)
        if snapshot:
          self.m.file.write_text('write version file', local_version_path,
                                 snapshot)
          self._mounted_snapshot = snapshot

      if not recipe_mount:
        self._reset_overlayfs_if_needed(cache_name)
      return recipe_mount_path

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
    item = (disk, instance, zone)
    if any(item in frame for frame in self._cleanup_gce_stack):
      return
    self._cleanup_gce_stack[-1].append(item)

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

  def get_instance_serial_output(self, instance, project, zone):
    with self.m.step.nest('get instance serial output') as presentation, \
        self.m.context(env={'VIRTUAL_ENV': '1'}):
      output = self.m.easy.stdout_step(
          'gcloud compute instances get-serial-port-output', [
              'gcloud', 'compute', 'instances', 'get-serial-port-output',
              instance, '--zone={}'.format(zone), '--project={}'.format(project)
          ], infra_step=True)
      presentation.logs['serial output'] = output

  def transactionally_update_recovery_image(self, image: str, cache_name: str,
                                            recovery_image: Optional[str]
                                           ) -> Optional[str]:
    """Transactionally update the recovery image to the provided image.

    The image name provided must already exist in GCP. The update does this:
      - quick double check to make sure the image exists.
      - copy the image to the recovery fallback path.
      - delete the old recovery image.
      - copy the newly created fallback image to the recovery image.
      - return the fallback image for later deletion.

    Args:
      image: the image to replace the recovery image with.
      cache_name: the name of the cache (just in case recovery image isn't
        provided).
      recovery_image: the name of the recovery image.

    Returns:
      The temp recovery disk to delete later.
    """
    if not self.image_exists(image):
      raise StepFailure('Asked to copy an image that does not exist')

    recovery_image_name = recovery_image or RECOVERY_IMAGE_TEMPLATE.format(
        cache_name)
    fallback_recovery_name = RECOVERY_IMAGE_FALLBACK_TEMPLATE.format(
        recovery_image_name)

    # If a previous build failed, we could still have the recovery image in here. If so, delete it.
    if self.image_exists(fallback_recovery_name):
      self.delete_image(fallback_recovery_name)
    # If there is no recovery image yet, we don't need to mess with the whole
    # swap approach.
    if not self.image_exists(recovery_image_name):
      # Just create the recovery image from the source.
      self.create_image_from_image(recovery_image_name, image)
      return None

    self.create_image_from_image(fallback_recovery_name, image)
    # Now that there's a fallback image, safely delete the recovery image.
    self.delete_image(recovery_image_name)
    # For thoroughness, use the fallback image to recreate the recovery image.
    self.create_image_from_image(recovery_image_name, fallback_recovery_name)
    # Return the recovery name for later deletion (not deleting now because of
    # race condition).
    return fallback_recovery_name

  def download_file(self, source_path: str, dest_path: str):
    """Download Google Storage object.

    Args:
      source_path: Google Storage path to copy (e.g. 'gs://my-bucket/file.txt')
      dest_path: Local path to save the object (e.g. '/tmp')
    """
    # TODO: not sure if this context is needed.
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.storage_cp(source_path, dest_path, step='download GS file')

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def storage_cp(self, source: str, dest: str, step: str = 'gcloud storage cp',
                 flags: Optional[List[str]] = None, **kwargs):
    """Do a gcloud storage cp.

    Args:
      source: source location to copy.
      dest: destination location to copy.
      step: step name.
      flags: additional command line flags.
      kwargs: additional arguments.
    """
    args = ['gcloud', 'storage', 'cp']
    if flags is not None:
      args.extend(flags)
    args.extend([source, dest])
    return self.m.step(step, args, **kwargs)

  def storage_ls(self, path: str):
    """Do a gcloud storage ls.

    Args:
      path: the path to ls.
    """
    return self.m.step('gcloud storage ls', ['gcloud', 'storage', 'ls', path],
                       ok_ret=(0, 1))
