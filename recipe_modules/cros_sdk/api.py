# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

import contextlib
import json
import os

from recipe_engine import recipe_api

from PB.chromiumos import common
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.packages import UprevPackagesRequest
from PB.chromite.api.sdk import CleanRequest as CleanSdkRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UnmountRequest as UnmountSdkRequest
from PB.chromite.api.sdk import CreateSnapshotRequest
from PB.chromite.api.sdk import RestoreSnapshotRequest


class CrosSdkApi(recipe_api.RecipeApi):
  """A module for interacting with cros_sdk."""

  def initialize(self):
    """Cache the chroot path."""
    self.configure(self.m.path['cache'])

  def configure(self, chroot_parent_path):
    """Configure CrosSdkApi.

    Args:
      chroot_parent_path (Path): Parent for chroot directory.
    """
    with self.m.step.nest('configure chroot path'):
      self._chroot_path = chroot_parent_path.join('cros_chroot')
      self.m.file.ensure_directory('ensure chroot directory', self._chroot_path)
      self._sdk_cache_version = None
      self._sdk_cache_version_file = self._chroot_path.join(
          'sdk_cache_version.json')
      self._chrome_root = None
      self._goma_dir = None
      self._goma_client_json = None
      self._goma_approach = None
      self._goma_log_dir = None
      self._goma_stats_file = None
      self._goma_counterz_file = None
      self._use_flags = None
      self._sdk_is_dirty = False

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.repo_resource('cros_sdk')

  @property
  def chroot(self):
    """Return a chromiumos.common.Chroot."""
    env = None
    if self._use_flags:
      env = common.Chroot.ChrootEnv(
          use_flags=self._use_flags
      )
    return common.Chroot(
        path=str(self._chroot_path),
        chrome_dir=self._chrome_root,
        env=env,
    )

  @property
  def sdk_cache_version(self):
    """Lazily load from file. Can be None if version file doesn't exist."""
    if self._sdk_cache_version == None:
      # Use os.path because version file pre-exists recipe run.
      if (os.path.exists(str(self._sdk_cache_version_file)) or
          self._test_data.enabled):
        version_json = self.m.file.read_json(
            name='read sdk cache version json',
            source=self._sdk_cache_version_file
        )
        self._sdk_cache_version = str(version_json['version'])
    return self._sdk_cache_version

  @sdk_cache_version.setter
  def sdk_cache_version(self, value):
    """Set sdk cache version and write to file.

    Args:
      * value (str): new sdk cache version to set.
    """
    tmp_file = self.m.path['cleanup'].join('sdk_cache_version.json')
    self.m.file.write_json(
        name='write sdk cache version file',
        dest=tmp_file,
        data={'version': str(value)},
    )
    cmd = [
        'sudo',
        'mv',
        tmp_file,
        self._sdk_cache_version_file,
    ]
    self.m.step('move sdk cache version file into place', cmd)
    self._sdk_cache_version = value;

  def set_chrome_root(self, chrome_root):
    self._chrome_root = chrome_root

  def set_goma_config(self, goma_dir, goma_client_json, goma_approach,
                      log_dir, stats_file, counterz_file):
    self._goma_dir = goma_dir
    self._goma_client_json = goma_client_json
    self._goma_approach = goma_approach
    self._goma_log_dir = log_dir
    self._goma_stats_file = stats_file
    self._goma_counterz_file = counterz_file

  def has_goma_config(self):
    return bool(self._goma_dir and self._goma_client_json)

  def goma_config(self):
    if not self.has_goma_config():
      return None

    return common.GomaConfig(
        goma_dir=str(self._goma_dir),
        goma_client_json=str(self._goma_client_json),
        goma_approach=self._goma_approach,
        log_dir=common.SyncedDir(dir=self._goma_log_dir),
        stats_file=self._goma_stats_file,
        counterz_file=self._goma_counterz_file,
    )

  def set_use_flags(self, use_flags):
    self._use_flags = use_flags

  def mark_sdk_as_dirty(self):
    self._sdk_is_dirty = True

  def __call__(self, name, args, **kwargs):
    """Executes 'cros_sdk' with the supplied arguments.

    Args:
      * name (str): The name of the step.
      * args (list): A list of arguments to supply to 'cros_sdk'.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      See 'step.__call__'.
    """
    cmd = [
        self.cros_sdk_path,
        '--chroot',
        self._chroot_path,
    ]

    cmd += args
    return self.m.step(name, cmd, **kwargs)

  def _delete_chroot(self, name=None):
    """Call SdkService.Delete.

    Args:
      name (string): step name. Default: 'delete sdk'.
    """
    with self.m.step.nest(name or 'delete sdk'):
      self.m.cros_build_api.SdkService.Delete(
          DeleteSdkRequest(chroot=self.chroot))

  def create_chroot(self, version=None, use_image=True, timeout_sec=40 * 60,
                    name=None):
    """Initialize the chroot and link it into the workspace.

    Args:
      version (int): Required SDK version, if any.  Some recipes do not care
          what version the SDK is, they just need any SDK.
      use_image (boolean): Mount the SDK file as an image.  Default: True.
      timeout_sec (int): Step timeout (in seconds).  Default: 40 minutes.
      name (str): Step name.  Default: 'init sdk'.

    Returns:
      chromiumos_pb2.Chroot protobuf for the chroot.
    """
    with self.m.step.nest(name or 'init sdk') as presentation:
      try:
        self.build_chmod_chroot()
        # Replace the chroot if necessary.
        replace = False
        if version:
          disk_version = self.sdk_cache_version
          presentation.logs['sdk cache version'] = [
              'Version in config: %s' % version,
              'Version on disk: %s' % disk_version,
          ]
          replace = str(version) != disk_version
        response = self.m.cros_build_api.SdkService.Create(
            CreateSdkRequest(
                flags=CreateSdkRequest.Flags(no_replace=not replace,
                                             no_use_image=not use_image),
                chroot=self.chroot), timeout=timeout_sec)
        presentation.logs['sdk version'] = str(response.version.version)
        if version:
          self.sdk_cache_version = version
        self.link_chroot(self.m.cros_source.workspace_path)
      except self.m.step.StepFailure:
        # Invalidate the cache if the InitSDK call fails.
        self._delete_chroot(name='InitSDK failure')
        raise
    return self.chroot

  # TODO(crbug.com/949721): Currently, chromite depends on the chroot
  # living within the source tree. As a workaround, link the external
  # chroot into the workspace to make it look legit. New chromite services
  # should accept the chroot path as a parameter.
  def link_chroot(self, checkout_path):
    """Link the chroot to a chromiumos checkout.

    Args:
      checkout_path (Path): Path to the checkout root.
    """
    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('link chroot in %s' % checkout_basename):
      self.m.file.ensure_directory('ensure %s' % checkout_basename,
                                   checkout_path)

      chroot_link = checkout_path.join('chroot')
      if self.m.path.exists(chroot_link):
        self.m.file.remove('remove original chroot link', chroot_link)

      self.m.file.symlink('link %s to chroot' % checkout_basename,
                          self._chroot_path, chroot_link)

  def update_chroot(self, commit, changes, build_source=False,
                    toolchain_changed=False, toolchain_targets=None,
                    timeout_sec='DEFAULT', name=None):
    """Update the chroot.

    Args:
      commit (GitilesCommit): Active gitiles_commit, or None.
      changes (list[GerritChange]): Active gerrit changes, or None.
      build_source (boolean): Whether to compile from source.  Default: False.
      toolchain_changed (boolean): Whether toolchain has changed.
          Default: False.
      toolchain_targets (list[BuildTarget]): List of toolchain targets needed,
          or None.
      timeout_sec (int): Step timeout (in seconds).  Default: None if a
          toolchain change is detected, otherwise 1 hour.
      name (string): Step name.  Default: "update sdk".

    Returns:
      (boolean) whether the toolchain was changed.
    """
    with self.m.step.nest(name or 'update sdk'):
      # If there are changes, they may affect the toolchain.
      if changes and not toolchain_changed:
        with self.m.step.nest('detect toolchain change') as detect:
          toolchain_changed = self.m.cros_relevance.check_for_toolchain_change(
              changes, commit, chroot=self.chroot)
          self.m.easy.set_property_step('testing_toolchain', toolchain_changed)
          detect.step_text = ('change detected'
                              if toolchain_changed else 'no change')
      if toolchain_changed:
        self.mark_sdk_as_dirty()
      flags = UpdateSdkRequest.Flags(build_source=build_source,
                                     toolchain_changed=toolchain_changed)
      if timeout_sec == 'DEFAULT':
        timeout_sec = None if toolchain_changed else 60 * 60
      try:
        self.m.cros_build_api.SdkService.Update(
            UpdateSdkRequest(chroot=self.m.cros_sdk.chroot, flags=flags,
                             toolchain_targets=toolchain_targets),
            timeout=timeout_sec)
      except self.m.step.StepFailure:
        # If the update fails, also delete the SDK.
        self._delete_chroot(name='UpdateSDK failure')
        raise
      return toolchain_changed

  @contextlib.contextmanager
  def cleanup_context(self, checkout_path=None):
    """Returns a context that cleans the SDK chroot named cache.

    Args:
      checkout_path (Path): Path to source checkout.  Default:
          cros_source.workspace_path.
    """
    try:
      yield
    except self.m.step.StepFailure:
      self.mark_sdk_as_dirty()
      raise
    finally:
      if self._sdk_is_dirty:
        self._delete_chroot(name='Invalidating SDK due to dirty state')

      with self.m.step.nest('clean up SDK chroot'):
        self.cleanup_sysroot()
        self.unmount_chroot()
        self.unlink_chroot(checkout_path or self.m.cros_source.workspace_path)
        self.swarming_chmod_chroot()

  @contextlib.contextmanager
  def snapshot(self):
    """Returns a context that snapshots and restores the SDK chroot state.

    When this context manager is entered, a snapshot is made of the chroot
    state and a token corresponding to that snapshot is stored. When the context
    is exited, regardless of the reason, the context manager will attempt to
    restore the chroot back to that initial snapshot. If the chroot was
    initially created with 'nouse-image', it will be replaced so that it
    supports the ability to make snapshots.
    """
    with self.m.step.nest('creating chroot snapshot'):
      snapshot_response = self.m.cros_build_api.SdkService.CreateSnapshot(
          CreateSnapshotRequest(chroot=self.chroot))
      snapshot_token = snapshot_response.snapshot_token

    try:
      yield
    finally:
      # Regardless of how we exited the context block, try to restore the
      # chroot snapshot.
      try:
        with self.m.step.nest('restoring chroot from snapshot'):
          self.m.cros_build_api.SdkService.RestoreSnapshot(
              RestoreSnapshotRequest(
                  chroot=self.chroot, snapshot_token=snapshot_token))
      except:
        # If restoring the snapshot fails for any reason, mark the current SDK
        # for deletion and reraise the exception.
        self.mark_sdk_as_dirty()
        raise

  def unmount_chroot(self):
    with self.m.step.nest('unmounting chroot'):
      self.m.cros_build_api.SdkService.Unmount(
          UnmountSdkRequest(chroot=self.chroot))

  def cleanup_sysroot(self):
    with self.m.step.nest('removing sysroot'):
      self.m.cros_build_api.SdkService.Clean(
          CleanSdkRequest(chroot=self.chroot))

  def unlink_chroot(self, checkout_path):
    """Unlink the chroot from the chromiumos checkout.

     Args:
      checkout_path (Path): Path to the checkout root.
    """
    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('unlink chroot in %s' % checkout_basename):
      chroot_link = checkout_path.join('chroot')
      if self.m.path.exists(chroot_link):
        self.m.file.remove('remove original chroot link', chroot_link)

  def swarming_chmod_chroot(self):
    """Chroot is deployed as root, therfore change permissions to
       allow for Swarming cache uninstall/install.
    """
    if self.m.path.exists(self._chroot_path):
      chmod_cmd = ['sudo', '-n', 'chmod', 'a+rwX,-t', self._chroot_path]
      self.m.step('changing permissions of %s' % self._chroot_path, chmod_cmd,
                  infra_step=True)

  def build_chmod_chroot(self):
    """Chroot needs to be tightened to 755 for the build process."""
    if self.m.path.exists(self._chroot_path):
      chmod_cmd = [
          'sudo', '-n', 'chmod', 'u=rwx,g=rx,o=rx,-t', self._chroot_path
      ]
      self.m.step('changing permissions of %s' % self._chroot_path, chmod_cmd,
                  infra_step=True)

  def run(self, name, cmd, env=None, workspace=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

    It is assumed the current working directory is within a chromiumos checkout.

    Args:
      * name (str): The name of the step.
      * cmd (list): A command and arguments to run.
      * env (dict): A dict of environment variables to pass to the command.
      * workspace (Path): A path to mount to the chroot's workspace directory.
      * kwargs: Keyword arguments to pass to __call__.

    Returns:
      See 'step.__call__'.
    """
    args = []
    if env is not None:
      args += ['%s=%s' % x for x in env.items()]
    args += ['--'] + cmd
    return self(name, args, **kwargs)

  def uprev_packages(self, build_targets=None, timeout_sec = 10 * 60,
                     name='uprev packages'):
    """Uprev packages.

    Args:
      build_targets (list[BuildTarget]): List of build_targets whose packages
          should be uprevved, or None for all build_targets.
      timeout_sec (int): Step timeout (in seconds).  Default: 10 minutes.
      name (string): Name for step.

    Returns:
      UprevPackagesResponse
    """
    with self.m.step.nest(name):
      return self.m.cros_build_api.PackageService.Uprev(
          UprevPackagesRequest(
              chroot=self.chroot, build_targets=build_targets,
              overlay_type=OVERLAYTYPE_BOTH),
          timeout=timeout_sec)
