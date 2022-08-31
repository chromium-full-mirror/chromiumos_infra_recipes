# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

from collections import namedtuple
import contextlib

from recipe_engine.recipe_api import RecipeApi, StepFailure

from PB.chromiumos import common
from PB.chromiumos.sdk_cache_state import SdkCacheState
from PB.chromite.api import toolchain
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.packages import UprevPackagesRequest
from PB.chromite.api.sdk import CleanRequest as CleanSdkRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UnmountRequest as UnmountSdkRequest
from PB.chromite.api.sdk import CreateSnapshotRequest
from PB.chromite.api.sdk import RestoreSnapshotRequest

# Default value for the sdk cache version
_DEFAULT_SDK_CACHE_VERSION = 1
_PRELOAD_PATH = '/preload'
_PRELOAD_CACHE_PATH = '/preload/chromeos-sdk'

_SDK_VERSION_PROJECT_PATH = 'src/third_party/chromiumos-overlay/chromeos/binhost/host/sdk_version.conf'
_SDK_VERSION_CONF_TEST_DATA = 'SDK_LATEST_VERSION="foo"\nTC_PATH="bar"\n'


class CrosSdkApi(RecipeApi):
  """A module for interacting with cros_sdk."""

  def __init__(self, props, *args, **kwargs):
    super(CrosSdkApi, self).__init__(*args, **kwargs)
    # TODO(b/169266654): Make this a git footer configurable value.
    self._force_off_toolchain_changed = props.force_off_toolchain_changed
    self._mount_named_cache = props.mount_named_cache
    self._chroot_initialized = False

  def initialize(self):
    """Cache the chroot path."""
    self._long_timeouts = False
    self.configure(self.m.path['cache'])
    self._mount_named_cache |= ('chromeos.cros_sdk.mount_named_cache' in
                                self.m.cros_infra_config.experiments)

  @property
  def force_off_toolchain_changed(self):
    """Return whether we are forcing toolchain_cls off for testing."""
    return self._force_off_toolchain_changed

  def configure(self, chroot_parent_path):
    """Configure CrosSdkApi.

    Args:
      chroot_parent_path (Path): Parent for chroot directory.
    """
    with self.m.step.nest('configure chroot path'):
      self._preload_cache_path = None
      self._preload_cache_state_file = None
      self._configure_preload_if_exists()
      self._cache_path = chroot_parent_path.join('cros_chroot')
      self._chroot_path = self._cache_path.join('chroot')
      self._sdk_cache_state = None
      self._sdk_cache_state_file = self._cache_path.join('sdk_cache_state.json')
      self._chrome_root = None
      self._reclient_dir = None
      self._reproxy_cfg_file = None
      self._remoteexec_config = None
      self._goma_dir = None
      self._goma_client_json = None
      self._goma_approach = None
      self._goma_log_dir = None
      self._goma_stats_file = None
      self._goma_counterz_file = None
      self._use_flags = None
      self._sdk_is_dirty = False

  def _configure_preload_if_exists(self):
    """Configures the preload cache path if the the preload directory exists."""
    if self._test_data.enabled and self._test_data.get('preload_path_exists',
                                                       True):
      self.m.path.mock_add_paths(_PRELOAD_PATH)
    if self.m.path.exists(_PRELOAD_PATH):
      self._preload_cache_path = _PRELOAD_CACHE_PATH
      self.m.file.ensure_directory('create preload path',
                                   self._preload_cache_path)
      self._preload_cache_state_file = self._preload_cache_path.join(
          'sdk_cache_state.json')

  @property
  def sdk_is_dirty(self):
    """Return whether the SDK is dirty"""
    return self._sdk_is_dirty

  @property
  def long_timeouts(self):
    """Return whether timeouts should be long.

    This can be caused by either source compile, or toolchain cls.
    """
    return self._long_timeouts

  @long_timeouts.setter
  def long_timeouts(self, value):
    """Set long_timeouts.

    This boolean is sticky.
    """
    self._long_timeouts |= value

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.repo_resource('cros_sdk')

  @property
  def chroot(self):
    """Return a chromiumos.common.Chroot."""
    env = None
    if self._use_flags:
      env = common.Chroot.ChrootEnv(use_flags=self._use_flags)
    return common.Chroot(
        path=str(self._chroot_path),
        chrome_dir=self.chrome_root,
        env=env,
    )

  @property
  def chrome_root(self):
    return str(self._chrome_root) if self._chrome_root else None

  @property
  def sdk_cache_state(self):
    """Returns default values if not set and cache state file does not exist."""
    if not self._sdk_cache_state:
      self._sdk_cache_state = self._read_sdk_cache_state_file(
          self._sdk_cache_state_file)
    return self._sdk_cache_state

  def _read_sdk_cache_state_file(self, path,
                                 step_name='read sdk cache state json'):
    """Read SdkCacheState proto from file.

    Args:
      path (Path): Path to read SdkCacheState file from.
      step_name (string): Name for the step.

    Returns:
      sdk_state (SdkCacheState): The SdkCacheState proto from the file or an
        SdkCacheProto with default values if the file does not exist.
    """
    self.m.path.mock_add_paths(path)
    sdk_state = SdkCacheState()
    if self.m.path.exists(self._sdk_cache_state_file):
      sdk_state = self.m.file.read_proto(step_name, self._sdk_cache_state_file,
                                         SdkCacheState, 'JSONPB')
      self.m.file.remove('remove sdk version file', self._sdk_cache_state_file)
    sdk_state.version = sdk_state.version or _DEFAULT_SDK_CACHE_VERSION
    return sdk_state

  def _write_sdk_cache_state(self, version=_DEFAULT_SDK_CACHE_VERSION):
    """Set sdk cache state and write to file.

    Args:
      version (int): new sdk cache version to set.
    """
    state = SdkCacheState(
        version=version,
        manifest_branch=self.m.cros_source.manifest_branch or 'snapshot',
        manifest_url=self.m.src_state.build_manifest.url,
        snapshot_hash=self.m.src_state.gitiles_commit.id,
    )
    self.m.file.write_proto('write sdk cache state file',
                            self._sdk_cache_state_file, state, 'JSONPB')
    self._sdk_cache_state = state

  def set_chrome_root(self, chrome_root):
    """Set chrome root with synced sources.

    This is a helper function to set up a chrome root.

    Args:
      chrome_root (Path): Directory with the Chrome source.
    """
    self._chrome_root = chrome_root

  def configure_goma(self):
    """Configure goma for Chrome.

    This is a helper function to do the various bits of cros_sdk configuration
    needed for Chrome to be built with goma.

    Must be run with cwd inside a chromiumos source root.
    """
    self.set_goma_config(self.m.goma.goma_dir, self.m.goma.goma_client_json,
                         self.m.goma.goma_approach,
                         self.m.path.mkdtemp(prefix='goma-logs-'),
                         'stats.binaryproto', 'counterz.binaryproto')

  def set_goma_config(self, goma_dir, goma_client_json, goma_approach, log_dir,
                      stats_file, counterz_file):
    """Set the goma config.

    Args:
      goma_dir (Path): Path to the goma install location.
      goma_client_json (Path): Path to the goma client credentials file.
      goma_approach (chromiumos.GomaConfig.GomaApproach): Goma Approach.
      log_dir (Path): Path to the log directory.
      stats_file (str): Name of the goma stats file, relative to log_dir.
      counterz_file (str): Name of the goma counterz file, relative to log_dir.
    """
    self._goma_dir = str(goma_dir)
    self._goma_client_json = str(goma_client_json)
    self._goma_approach = goma_approach
    self._goma_log_dir = str(log_dir)
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

  def configure_remoteexec(self):
    """Configure remoteexec for Chrome."""
    self.set_remoteexec_config(self.m.remoteexec.reclient_dir,
                               self.m.remoteexec.reproxy_cfg_file)

  def set_remoteexec_config(self, reclient_dir, reproxy_cfg_file):
    """Set the remoteexec config."""
    if reclient_dir and reproxy_cfg_file:
      self._remoteexec_config = common.RemoteexecConfig(
          reclient_dir=str(reclient_dir),
          reproxy_cfg_file=str(reproxy_cfg_file))
    else:
      raise ValueError('Both reclient_dir %s and reproxy_cfg_file %s required' %
                       (reclient_dir, reproxy_cfg_file))

  def has_remoteexec_config(self):
    return self._remoteexec_config is not None

  @property
  def remoteexec_config(self):
    return self._remoteexec_config

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

  def _remove_chroot(self, name=None):
    with self.m.step.nest(name or 'remove sdk'):
      self.cleanup_sysroot()
      self.unmount_chroot()
      self._delete_chroot()

  def _delete_chroot(self, name=None):
    """Call SdkService.Delete.

    Args:
      name (string): step name. Default: 'delete sdk'.
    """
    with self.m.step.nest(name or 'delete sdk'):
      self.m.cros_build_api.SdkService.Delete(
          DeleteSdkRequest(chroot=self.chroot))

  def _is_chroot_usable(self, cache_state, version, step_logs):
    """Determine whether the cached version of the chroot can be reused.

    Compare the config's sdk version and manifest branch to the ones in the
    given SdkCacheState. If they are the same the cached chroot can be reused.

    Args:
      cache_state (SdkCacheState): The state of the cached chroot of
          interest.
      version (int): Required SDK cache version, if any. Some recipes do not
          care what version the SDK is, they just need any SDK.
      step_logs (dict): The logs dict of the calling step.

    Returns:
      Boolean indicating if the chroot can be reused.
    """
    step_logs['sdk cache version'] = [
        'Version in config: %d' % version,
        'Version on disk: %d' % cache_state.version,
    ]
    step_logs['sdk manifest url'] = [
        'Url in config: %s' % self.m.src_state.build_manifest.url,
        'Url on disk: %s' % cache_state.manifest_url
    ]
    step_logs['sdk manifest branch'] = [
        'Branch in config: %s' % self.m.cros_source.manifest_branch or
        'snapshot',
        'Branch on disk: %s' % cache_state.manifest_branch
    ]
    step_logs['sdk snapshot hash'] = [
        'Snapshot hash in config: %s' % self.m.src_state.gitiles_commit.id,
        'Snapshot hash on disk: %s' % cache_state.snapshot_hash
    ]

    if self._test_data.enabled:
      reuse = self._test_data.get('is_chroot_usable', None)
      if reuse:
        return reuse.pop(0)

    reuse = True
    reuse &= (version == cache_state.version)
    manifest_branch = self.m.cros_source.manifest_branch or 'snapshot'
    reuse &= (manifest_branch == cache_state.manifest_branch)
    reuse &= (self.m.src_state.build_manifest.url == cache_state.manifest_url)
    with self.m.context(cwd=self.m.src_state.build_manifest.path):
      reuse &= (
          bool(cache_state.snapshot_hash) and
          self.m.git.is_reachable(cache_state.snapshot_hash.strip(),
                                  head=self.m.src_state.gitiles_commit.id))
    return reuse

  def _check_sdk_cache_state(self, version):
    """Check if any cached SDK can be reused for the build.

    Args:
      version (int): Required SDK cache version, if any. Some recipes do not
          care what version the SDK is, they just need any SDK.

    Returns:
      reuse (bool): Whether a cached version of the chroot can be reused for the
          build.
    """
    with self.m.step.nest('check SDK in named cache') as presentation:
      reuse = self._is_chroot_usable(self.sdk_cache_state, version,
                                     presentation.logs)
      if reuse:
        presentation.properties['sdk_cache'] = 'cros_chroot'
        return reuse

      # TODO(crbug.com/1167322): Remove check for self_mount_named_cache when
      # mount_named_cache is no longer an experiment and all prod builders use
      # an image with the preload SDK.
      if not self._preload_cache_path or not self._mount_named_cache:
        presentation.properties['sdk_cache'] = 'none'
        return reuse

    with self.m.step.nest('check SDK in preload cache') as presentation:
      preload_cache = self._read_sdk_cache_state_file(
          self._preload_cache_state_file)
      reuse = self._is_chroot_usable(preload_cache, version, presentation.logs)
      if not reuse:
        presentation.properties['sdk_cache'] = 'none'
        return reuse

      presentation.properties['sdk_cache'] = 'preload'
      self._remove_chroot('delete SDK in named cache')
      self.unlink_chroot(self.m.cros_source.workspace_path)
      self.m.overlayfs.unmount('cros_chroot', self._cache_path)
      self.m.step('deleting named cache',
                  ['sudo', '-n', 'rm', '-rf', self._cache_path])
      self.m.overlayfs.mount('cros_chroot', self._preload_cache_path,
                             self._cache_path, persist=True)
      return reuse

  def create_chroot(self, version=None, use_image=True, bootstrap=False,
                    sdk_version=None, timeout_sec='DEFAULT', test_data=None,
                    test_toolchain_cls=None, name=None):
    """Initialize the chroot and link it into the workspace.

    Create a chroot if one does not already exist in the chroot path. If one
    already exists, but is not reusable by this build (see _ensure_cache_state)
    delete the existing chroot and create a new one.

    Args:
      version (int): Required SDK cache version, if any.  Some recipes do not
          care what version the SDK is, they just need any SDK.
      use_image (boolean): Mount the SDK file as an image.  Default: True.
      bootstrap (boolean): Whether to bootstrap the chroot.  Default: False
      sdk_version (string): Optional. Specific SDK version to include in the
        CreateSdkRequest, e.g. 2022.01.20.073008.
      timeout_sec (int): Step timeout (in seconds).  Default: None if
          bootstrap is True, otherwise 3 hours.
      test_data (str): test response (JSON) from the SdkService.Create call, or
          None to use the default in cros_build_api/test_api.py.
      test_toolchain_cls (bool): Test answer for detect_toolchain_cls.
      name (str): Step name.  Default: 'init sdk'.

    Returns:
      chromiumos_pb2.Chroot protobuf for the chroot.
    """
    # If the builder's config does not have an sdk_cache_version specified, it
    # is version _DEFAULT_SDK_CACHE_VERSION (1).  (Once we need to bump the
    # cache version, the config will have it for everyone.)
    version = version or _DEFAULT_SDK_CACHE_VERSION
    with self.m.step.nest(name or 'init sdk') as presentation:
      try:
        self.build_chmod_chroot()
        if timeout_sec == 'DEFAULT':
          timeout_sec = None if bootstrap else 180 * 60

        # Determine whether a cached root could be reused.
        # If we're requesting a specific SDK version, we probably want to
        # rebuild the chroot regardless.
        no_replace = self._check_sdk_cache_state(version) and not sdk_version
        # SdkService/Create will create a chroot if one does not already exist
        # or no_replace is False.
        response = self.m.cros_build_api.SdkService.Create(
            CreateSdkRequest(
                flags=CreateSdkRequest.Flags(no_replace=no_replace,
                                             no_use_image=not use_image,
                                             bootstrap=bootstrap),
                chroot=self.chroot, sdk_version=sdk_version),
            timeout=timeout_sec, test_output_data=test_data)
        presentation.logs['sdk version'] = str(response.version.version)
        self._chroot_initialized = True
        self._write_sdk_cache_state(version)
        self.link_chroot(self.m.cros_source.workspace_path)

        # If there were toolchain changes already applied to the workspace, we
        # can finally detect that.
        if self.m.workspace_util.detect_toolchain_cls(
            self.chroot, test_value=test_toolchain_cls):
          self.mark_sdk_as_dirty()

      except StepFailure:
        # Invalidate the cache if the InitSDK call fails.
        self._remove_chroot(name='InitSDK failure')
        raise

    return self.chroot

  # TODO(crbug.com/949721): Currently, chromite depends on the chroot
  # living within the source tree. As a workaround, link the external
  # chroot into the workspace to make it look legit. New chromite services
  # should accept the chroot path as a parameter.
  def link_chroot(self, checkout_path, chroot_path=None):
    """Link the chroot to a chromiumos checkout.

    Args:
      checkout_path (Path): Path to the checkout root.
      chroot_path (Path): Path to the chroot, or None for the default.
    """
    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('link chroot in %s' % checkout_basename):
      self.m.file.ensure_directory('ensure %s' % checkout_basename,
                                   checkout_path)

      chroot_link = checkout_path.join('chroot')
      if self.m.path.exists(chroot_link):
        self.m.file.remove('remove original chroot link', chroot_link)

      self.m.file.symlink('link %s to chroot' % checkout_basename,
                          chroot_path or self._chroot_path, chroot_link)

  def update_chroot(self, commit, changes, build_source=False,
                    toolchain_targets=None, timeout_sec='DEFAULT',
                    test_data=None, test_toolchain_cls=None, name=None):
    """Update the chroot.

    Args:
      commit (GitilesCommit): Active gitiles_commit, or None.
      changes (list[GerritChange]): Active gerrit changes, or None.
      build_source (boolean): Whether to compile from source.  Default: False.
      toolchain_targets (list[BuildTarget]): List of toolchain targets needed,
          or None.
      timeout_sec (int): Step timeout (in seconds), or None for no step timeout.
          Default: 24 hours if building from source or a toolchain change is
          detected, otherwise 3 hours.
      test_data (str): test response (JSON) from the SdkService.Update call, or
          None to use the default in cros_build_api/test_api.py.
      test_toolchain_cls (bool): Test answer for detect_toolchain_cls.
      name (string): Step name.  Default: "update sdk".
    """
    with self.m.step.nest(name or 'update sdk') as pres:
      # See if any of the changes affect the toolchain.
      toolchain_cls = self.m.workspace_util.detect_toolchain_cls(
          self.chroot, commit, changes, test_value=test_toolchain_cls)
      if build_source or toolchain_cls:
        self.mark_sdk_as_dirty()
        self._long_timeouts = True
      if self.force_off_toolchain_changed:
        pres.step_text = 'Forcing toolchain_changed=False'
        toolchain_cls = False
      if timeout_sec == 'DEFAULT':
        timeout_sec = 24 * 60 * 60 if self._long_timeouts else 180 * 60

      try:
        self.m.cros_build_api.SdkService.Update(
            UpdateSdkRequest(
                chroot=self.chroot, toolchain_targets=toolchain_targets,
                flags=UpdateSdkRequest.Flags(build_source=build_source,
                                             toolchain_changed=toolchain_cls)),
            timeout=timeout_sec, test_output_data=test_data)
      except StepFailure:
        # If the update fails, also delete the SDK.
        self._remove_chroot(name='UpdateSDK failure')
        raise

  @contextlib.contextmanager
  def cleanup_context(self, checkout_path=None):
    """Returns a context that cleans the SDK chroot named cache.

    This may be called before cros_source.ensure_synced_cache, since it yields
    immediately, and only accesses checkout_path during cleanup.

    Args:
      checkout_path (Path): Path to source checkout.  Default:
          cros_source.workspace_path.
    """
    if self._mount_named_cache and self._preload_cache_path:
      self.m.overlayfs.mount('cros_chroot', self._preload_cache_path,
                             self._cache_path, persist=True)
    self.m.file.ensure_directory('ensure chroot directory', self._chroot_path)
    try:
      yield
    except StepFailure:
      self.mark_sdk_as_dirty()
      raise
    finally:
      with self.m.step.nest('clean up SDK chroot'):
        if self._chroot_initialized:
          self.cleanup_sysroot()
          self.unmount_chroot()

          if self._sdk_is_dirty:
            self._delete_chroot(name='Invalidating SDK due to dirty state')

          self.unlink_chroot(checkout_path or self.m.cros_source.workspace_path)
          self.swarming_chmod_chroot()
          if self._mount_named_cache and self._preload_cache_path:
            self.m.overlayfs.unmount('cros_chroot', self._cache_path)

          if not self._test_data.get('is_chroot_usable', []) == []:
            raise StepFailure('not all input test data used')
        else:
          self._delete_chroot(name='ensure no rogue SDK')

  @contextlib.contextmanager
  def snapshot(self, create_test_data=None, restore_test_data=None):
    """Returns a context that snapshots and restores the SDK chroot state.

    When this context manager is entered, a snapshot is made of the chroot
    state and a token corresponding to that snapshot is stored. When the context
    is exited, regardless of the reason, the context manager will attempt to
    restore the chroot back to that initial snapshot. If the chroot was
    initially created with 'nouse-image', it will be replaced so that it
    supports the ability to make snapshots.

    Args:
      create_test_data (str): test response (JSON) from the
          SdkService.CreateSnapshot call, or None to use the default in
          cros_build_api/test_api.py.
      restore_test_data (str): test response (JSON) from the
          SdkService.RestoreSnapshot call, or None to use the default in
          cros_build_api/test_api.py.
    """
    SdkService = self.m.cros_build_api.SdkService
    with self.m.step.nest('creating chroot snapshot'):
      if self.m.cros_build_api.has_endpoint(SdkService, 'CreateSnapshot'):
        snapshot_response = SdkService.CreateSnapshot(
            CreateSnapshotRequest(chroot=self.chroot),
            test_output_data=create_test_data)
        snapshot_token = snapshot_response.snapshot_token
      else:
        raise StepFailure('Build API lacks SdkService.CreateSnaphsot endpoint')

    try:
      yield
    finally:
      # Regardless of how we exited the context block, try to restore the
      # chroot snapshot.
      try:
        with self.m.step.nest('restoring chroot from snapshot'):
          SdkService.RestoreSnapshot(
              RestoreSnapshotRequest(chroot=self.chroot,
                                     snapshot_token=snapshot_token),
              test_output_data=restore_test_data)
      except:
        # If restoring the snapshot fails for any reason, mark the current SDK
        # for deletion and reraise the exception.
        self.mark_sdk_as_dirty()
        raise

  def unmount_chroot(self, chroot=None):
    chroot = chroot or self.chroot
    with self.m.step.nest('unmounting chroot'):
      self.m.cros_build_api.SdkService.Unmount(UnmountSdkRequest(chroot=chroot))

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

  def run(self, name, cmd, env=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

    It is assumed the current working directory is within a chromiumos checkout.

    Args:
      * name (str): The name of the step.
      * cmd (list): A command and arguments to run.
      * env (dict): A dict of environment variables to pass to the command.
      * kwargs: Keyword arguments to pass to __call__.

    Returns:
      See 'step.__call__'.
    """
    args = []
    if env is not None:
      args += ['%s=%s' % x for x in env.items()]
    args += ['--'] + cmd
    return self(name, args, **kwargs)

  def uprev_packages(self, build_targets=None, timeout_sec=10 * 60,
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
          UprevPackagesRequest(build_targets=build_targets,
                               overlay_type=OVERLAYTYPE_BOTH),
          timeout=timeout_sec)

  def _parse_sdk_version(self):
    """Parse information from the sdk_version.conf file.

    Returns:
      (dict) mapping between fields and values found in the file.
    """
    filepath = self.m.cros_source.workspace_path.join(_SDK_VERSION_PROJECT_PATH)
    lines = self.m.file.read_text(
        'read sdk_version.conf', filepath,
        test_data=_SDK_VERSION_CONF_TEST_DATA).strip().split('\n')

    vals = {}
    for line in lines:
      if line.strip().startswith('#') or not line.strip():
        continue
      if '=' in line:
        toks = line.strip().split('=')
        vals[toks[0]] = toks[1].strip('"')
    return vals

  ToolchainInfo = namedtuple('ToolchainInfo',
                             ['sdk_version', 'toolchain_url', 'toolchains'])

  def get_toolchain_info(self, build_target):
    """Retrieve metadata about SDK/toolchain usage.

    Args:
      build_target (str): Name of the build target.

    Returns:
      (ToolchainInfo) information about sdk/toolchain usage.
    """
    with self.m.step.nest('get toolchain info'):

      sdk_info = self._parse_sdk_version()
      sdk_version = sdk_info.get('SDK_LATEST_VERSION', None)
      toolchain_url = sdk_info.get('TC_PATH', None)

      if sdk_version is None or toolchain_url is None:
        raise StepFailure('misformatted sdk_version.conf file')

      req = toolchain.ToolchainsRequest(board=build_target)
      resp = self.m.cros_build_api.ToolchainService.GetToolchainsForBoard(
          req, infra_step=True, test_output_data='{}')
      toolchains = (
          list(resp.default_toolchains) + list(resp.nondefault_toolchains))

      return self.ToolchainInfo(sdk_version, toolchain_url, toolchains)
