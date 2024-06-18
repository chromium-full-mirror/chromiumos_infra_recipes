# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

import contextlib
import dataclasses
from typing import Dict, List

from recipe_engine.recipe_api import RecipeApi, StepFailure

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.sdk_cache_state import SdkCacheState
from PB.chromite.api import sysroot
from PB.chromite.api import toolchain
from PB.chromite.api.sdk import CleanRequest as CleanSdkRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest

# Default value for the sdk cache version
_DEFAULT_SDK_CACHE_VERSION = 1

# Info for the source-controlled SDK verison file.
_SDK_VERSION_PROJECT_PATH = 'src/third_party/chromiumos-overlay/chromeos/binhost/host/sdk_version.conf'
_SDK_VERSION_CONF_TEST_DATA = 'SDK_LATEST_VERSION="foo"\nTC_PATH="bar"\n'

# TODO(b/187787264): On old branches, chromite may still depend on the chroot
# living within the source tree. We provide a symlink only for checkouts before
# this milestone. Remove when old milestones are no longer supported.
_MILESTONE_NEEDS_CHROOT_SYMLINK = 118


@dataclasses.dataclass
class ToolchainInfo:
  """Dataclass to hold info about the toolchain and SDK.

  Attributes:
    sdk_version: The SDK version used by the current build.
    sdk_bucket: The Google Storage bucket containing the above SDK.
    toolchain_url: The URL template for toolchains used by the current build.
    toolchains: A list of toolchains used.
  """
  sdk_version: str
  sdk_bucket: str
  toolchain_url: str
  toolchains: List[str]


class CrosSdkApi(RecipeApi):
  """A module for interacting with cros_sdk."""

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # TODO(b/169266654): Make this a git footer configurable value.
    self._force_off_toolchain_changed = props.force_off_toolchain_changed
    self._long_timeouts = props.force_long_timeouts
    self._chroot_initialized = False

  def initialize(self):
    """Cache the chroot path."""
    self.configure(self.m.path.cache_dir)

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
      self._cache_path = chroot_parent_path / 'cros_chroot'
      self._chroot_path = self._cache_path / 'chroot'
      self._out_path = self._cache_path / 'out'
      self._sdk_cache_state = None
      self._sdk_cache_state_file = self._cache_path / 'sdk_cache_state.json'
      self._chrome_root = None
      self._reclient_dir = None
      self._reproxy_cfg_file = None
      self._remoteexec_config = None
      self._goma_dir = None
      self._goma_approach = None
      self._goma_log_dir = None
      self._goma_stats_file = None
      self._goma_counterz_file = None
      self._use_flags = None
      self._sdk_is_dirty = False

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
    """Return a chromiumos.common.Chroot.

    Note that use of the Chroot's component fields (e.g., Chroot.path or
    Chroot.out_path) on an individual basis (such as os.path.join(Chroot.path,
    "tmp")) is usually incorrect. Recipes should not be making assumptions
    about the chroot path structure, and instead should funnel requests through
    the Build API, where inputs and outputs are represented in proto messages,
    and the API layer does any translation or copying of artifacts in and out
    of the chroot.
    """
    env = None
    if self._use_flags:
      env = common.Chroot.ChrootEnv(use_flags=self._use_flags)
    return common.Chroot(
        path=str(self._chroot_path),
        out_path=str(self._out_path),
        chrome_dir=self.chrome_root,
        env=env,
    )

  @property
  def chrome_root(self):
    return str(self._chrome_root) if self._chrome_root else None

  @property
  def default_sdk_sysroot(self):
    """Returns the default SDK Sysroot."""
    return sysroot.Sysroot(path='/')

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

  def _write_sdk_cache_state(self):
    """Set sdk cache state and write to file.

    Args:
      version (int): new sdk cache version to set.
    """
    if self.sdk_is_dirty or not self._sdk_cache_state:
      return
    self.m.file.write_proto('write sdk cache state file',
                            self._sdk_cache_state_file, self._sdk_cache_state,
                            'JSONPB')

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
    self.set_goma_config(self.m.goma.goma_dir, self.m.goma.goma_approach,
                         self.m.path.mkdtemp(prefix='goma-logs-'),
                         'stats.binaryproto', 'counterz.binaryproto')

  def set_goma_config(self, goma_dir, goma_approach, log_dir, stats_file,
                      counterz_file):
    """Set the goma config.

    Args:
      goma_dir (Path): Path to the goma install location.
      goma_approach (chromiumos.GomaConfig.GomaApproach): Goma Approach.
      log_dir (Path): Path to the log directory.
      stats_file (str): Name of the goma stats file, relative to log_dir.
      counterz_file (str): Name of the goma counterz file, relative to log_dir.
    """
    self._goma_dir = str(goma_dir) if goma_dir is not None else None
    self._goma_approach = goma_approach
    self._goma_log_dir = str(log_dir)
    self._goma_stats_file = stats_file
    self._goma_counterz_file = counterz_file

  def has_goma_config(self):
    return bool(self._goma_dir)

  def goma_config(self):
    if not self.has_goma_config():
      return None

    return common.GomaConfig(
        goma_dir=str(self._goma_dir),
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
    self.m.easy.set_properties_step(sdk_state='DIRTY')
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
        '--out-dir',
        self._out_path,
    ]

    cmd += args
    return self.m.step(name, cmd, **kwargs)

  def _remove_chroot(self, name=None):
    with self.m.step.nest(name or 'remove sdk'):
      self.cleanup_sysroot()
      self._delete_chroot()

  def _delete_chroot(self, name=None):
    """Call SdkService.Delete.

    Args:
      name (string): step name. Default: 'delete sdk'.
    """
    with self.m.step.nest(name or 'delete sdk'):
      self.m.cros_build_api.SdkService.Delete(
          DeleteSdkRequest(chroot=self.chroot))

  def create_chroot(self, version=None, bootstrap=False, sdk_version=None,
                    timeout_sec='DEFAULT', test_data=None,
                    test_toolchain_cls=None, name=None,
                    no_delete_out_dir=False):
    """Initialize the chroot and link it into the workspace.

    Create a chroot if one does not already exist in the chroot path. If one
    already exists, but is not reusable by this build (see _ensure_cache_state)
    or replace is True, delete the existing chroot and create a new one.

    Args:
      version (int): Required SDK cache version, if any.  Some recipes do not
          care what version the SDK is, they just need any SDK.
      bootstrap (boolean): Whether to bootstrap the chroot.  Default: False
      sdk_version (string): Optional. Specific SDK version to include in the
        CreateSdkRequest, e.g. 2022.01.20.073008.
      timeout_sec (int): Step timeout (in seconds).  Default: None if
          bootstrap is True, otherwise 3 hours.
      test_data (str): test response (JSON) from the SdkService.Create call, or
          None to use the default in cros_build_api/test_api.py.
      test_toolchain_cls (bool): Test answer for detect_toolchain_cls.
      name (str): Step name.  Default: 'init sdk'.
      no_delete_out_dir (boolean): If True, `out` directory will be preserved.

    Returns:
      chromiumos_pb2.Chroot protobuf for the chroot.
    """
    # If the builder's config does not have an sdk_cache_version specified, it
    # is version _DEFAULT_SDK_CACHE_VERSION (1).  (Once we need to bump the
    # cache version, the config will have it for everyone.)
    version = version or _DEFAULT_SDK_CACHE_VERSION
    with self.m.step.nest(name or 'init sdk') as presentation, \
             self.m.context(infra_steps=True):
      try:
        self.build_chmod_chroot()
        if timeout_sec == 'DEFAULT':
          timeout_sec = None if bootstrap else 180 * 60

        # SdkService/Create will create a chroot if one does not already exist
        # or no_replace is False.
        # TODO(b/266878468): drop no_use_image.
        response = self.m.cros_build_api.SdkService.Create(
            CreateSdkRequest(
                flags=CreateSdkRequest.Flags(
                    no_use_image=True, bootstrap=bootstrap,
                    no_delete_out_dir=no_delete_out_dir), chroot=self.chroot,
                sdk_version=sdk_version, skip_chroot_upgrade=True,
                ccache_disable=True), timeout=timeout_sec,
            test_output_data=test_data)
        presentation.logs['sdk version'] = str(response.version.version)
        self._chroot_initialized = True
        self.link_chroot(self.m.cros_source.workspace_path)

        # If there were toolchain changes already applied to the workspace, we
        # can finally detect that.
        if self.m.workspace_util.detect_toolchain_cls(
            self.chroot, test_value=test_toolchain_cls):
          self.mark_sdk_as_dirty()

        if not self.sdk_is_dirty:
          # If we succeeded in creating the SDK and it is not dirty yet then
          # record the cache state data.
          # It will be written to the SDK cache state file if the build succeeds
          # and it did not get marked as dirty later on.
          self._sdk_cache_state = SdkCacheState(
              version=version,
              manifest_branch=self.m.cros_source.manifest_branch or 'snapshot',
              manifest_url=self.m.src_state.build_manifest.url,
              snapshot_hash=self.m.src_state.gitiles_commit.id,
          )

      except StepFailure:
        # Invalidate the cache if the InitSDK call fails.
        self._remove_chroot(name='InitSDK failure')
        raise

    return self.chroot

  # TODO(b/187787264): On old branches, chromite may still depend on the chroot
  # living within the source tree. As a workaround, link the external chroot
  # into the workspace to make it look legit.
  def link_chroot(self, checkout_path, chroot_path=None):
    """Link the chroot to a chromiumos checkout.

    Args:
      checkout_path (Path): Path to the checkout root.
      chroot_path (Path): Path to the chroot, or None for the default.
    """
    # TODO(b/187787264): Remove when old branches are dead.
    if self.m.cros_version.version.milestone >= _MILESTONE_NEEDS_CHROOT_SYMLINK:
      return

    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('link chroot in %s' % checkout_basename):
      self.m.file.ensure_directory('ensure %s' % checkout_basename,
                                   checkout_path)

      chroot_link = checkout_path / 'chroot'
      if self.m.path.exists(chroot_link):
        self.m.file.remove('remove original chroot link', chroot_link)

      self.m.file.symlink('link %s to chroot' % checkout_basename,
                          chroot_path or self._chroot_path, chroot_link)

  def update_chroot(self, build_source=False, toolchain_targets=None,
                    timeout_sec='DEFAULT', test_data=None,
                    test_toolchain_cls=None, name=None, force_update=False):
    """Update the chroot.

    Args:
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
      force_update (bool): Pass force_update to the SdkService/Update call,
          causing update_chroot to be called.
    """
    with self.m.step.nest(name or 'update sdk') as pres:
      # See if any of the changes affect the toolchain.
      toolchain_cls = self.m.workspace_util.detect_toolchain_cls(
          self.chroot, test_value=test_toolchain_cls)

      builder_config = self.m.cros_infra_config.config_or_default
      use_snapshot_binhosts = builder_config.id.type == BuilderConfig.Id.CQ
      force_update = force_update or builder_config.build.sdk_update.sdknext

      if build_source or toolchain_cls or force_update:
        self.mark_sdk_as_dirty()
        self._long_timeouts = True
      if self.force_off_toolchain_changed:
        pres.step_text = 'Forcing toolchain_changed=False'
        toolchain_cls = False
      if timeout_sec == 'DEFAULT':
        timeout_sec = 24 * 60 * 60 if self._long_timeouts else 180 * 60

      chroot_without_use_flags = self.chroot
      chroot_without_use_flags.env.ClearField('use_flags')
      request = UpdateSdkRequest(
          chroot=chroot_without_use_flags, toolchain_targets=toolchain_targets,
          flags=UpdateSdkRequest.Flags(build_source=build_source,
                                       toolchain_changed=toolchain_cls,
                                       force_update=force_update),
          result_path=common.ResultPath(
              path=common.Path(
                  path=str(self.m.path.mkdtemp()),
                  location=common.Path.OUTSIDE)),
          use_snapshot_binhosts=use_snapshot_binhosts)
      try:
        response = self.m.cros_build_api.SdkService.Update(
            request, timeout=timeout_sec, test_output_data=test_data)
        pres.properties['skipped'] = response.skipped
        # Check if the SdkService/Update call failed to compile any packages.
        # If so, output the failed package data and then raise an exception.
        # Context: If a package failed to compile, the Build API call will have
        # a return code of 2 which does not automatically throw an exception.
        pkgs = self.m.cros_build_api.failed_pkg_logs(request, response)
        cl_affected_packages = []
        if pkgs and self.m.workspace_util.patch_sets:
          cl_affected_packages = self.m.cros_relevance.get_package_dependencies(
              self.default_sdk_sysroot, self.chroot,
              self.m.workspace_util.patch_sets, include_rev_deps=True)
        self.m.image_builder_failures.set_compile_failed_packages(
            pres, pkgs, cl_affected_packages)
      except StepFailure as e:
        # If the update fails, also delete the SDK.
        self._remove_chroot(name='UpdateSDK failure')
        raise e

  @contextlib.contextmanager
  def cleanup_context(self, checkout_path=None):
    """Returns a context that cleans the SDK chroot named cache.

    This may be called before cros_source.ensure_synced_cache, since it yields
    immediately, and only accesses checkout_path during cleanup.

    Args:
      checkout_path (Path): Path to source checkout.  Default:
          cros_source.workspace_path.
    """
    failing_build_exception = None
    self.m.file.ensure_directory('ensure chroot directory', self._chroot_path)
    try:
      yield
    except StepFailure as sf:
      failing_build_exception = sf
      self.mark_sdk_as_dirty()
    finally:
      with self.m.step.nest('clean up SDK chroot'):
        try:
          if self._chroot_initialized:
            self.cleanup_sysroot()
            self._write_sdk_cache_state()

            if self._sdk_is_dirty:
              self._delete_chroot(name='Invalidating SDK due to dirty state')

            self.unlink_chroot(checkout_path or
                               self.m.cros_source.workspace_path)
            self.swarming_chmod_chroot()
          else:
            self._delete_chroot(name='ensure no rogue SDK')

        # If cleaning up the SDK threw an exception, surface that exception
        # unless there was an earlier exception.
        except StepFailure as sf:
          raise failing_build_exception or sf

      # Finally, raise any exception that has yet to be raised.
      if failing_build_exception:
        raise failing_build_exception

  def cleanup_sysroot(self):
    # Unmount the bazel cache bind-mount before calling SdkService.Clean.
    # It attempts to delete the whole cache directory and fails if it
    # contains mount points.
    self.m.step(
        'unmount bazel cache dir',
        [
            'sudo',
            '-n',
            'umount',
            '--lazy',
            self.m.cros_source.workspace_path / '.cache/bazel',
        ],
        infra_step=True,
        # Ignore errors caused when the bind-mount does not exist or has been
        # already unmounted. Even if we fail to unmount the existing bind-mount
        # for some runtime errors, it is okay to suppress them because the
        # following SdkService.Clean will report an error and makes the whole
        # step fail anyway.
        ok_ret='any',
    )

    with self.m.step.nest('removing sysroot'):
      self.m.cros_build_api.SdkService.Clean(
          CleanSdkRequest(chroot=self.chroot))

  def unlink_chroot(self, checkout_path):
    """Unlink the chroot from the chromiumos checkout.

     Args:
      checkout_path (Path): Path to the checkout root.
    """
    # TODO(b/187787264): Remove when old branches are dead.
    if self.m.cros_version.version.milestone >= _MILESTONE_NEEDS_CHROOT_SYMLINK:
      return

    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('unlink chroot in %s' % checkout_basename):
      chroot_link = checkout_path / 'chroot'
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

  def _parse_sdk_version(self) -> Dict[str, str]:
    """Parse information from the sdk_version.conf file.

    Returns:
      A dict representing fields and values found in the file.
    """
    filepath = self.m.cros_source.workspace_path / _SDK_VERSION_PROJECT_PATH
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

  def get_toolchain_info(self, build_target: str) -> ToolchainInfo:
    """Retrieve metadata about SDK/toolchain usage.

    Args:
      build_target: Name of the build target.

    Returns:
      Information about sdk/toolchain usage.
    """
    with self.m.step.nest('get toolchain info'):

      sdk_info = self._parse_sdk_version()
      sdk_version = sdk_info.get('SDK_LATEST_VERSION', None)
      sdk_bucket = sdk_info.get('SDK_BUCKET', '')
      toolchain_url = sdk_info.get('TC_PATH', None)

      if sdk_version is None or toolchain_url is None:
        raise StepFailure('misformatted sdk_version.conf file')

      req = toolchain.ToolchainsRequest(board=build_target)
      resp = self.m.cros_build_api.ToolchainService.GetToolchainsForBoard(
          req, infra_step=True, test_output_data='{}')
      toolchains = (
          list(resp.default_toolchains) + list(resp.nondefault_toolchains))

      return ToolchainInfo(sdk_version=sdk_version, sdk_bucket=sdk_bucket,
                           toolchain_url=toolchain_url, toolchains=toolchains)
