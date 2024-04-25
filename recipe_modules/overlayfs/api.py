# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with OverlayFS mounts (the Linux 'overlay' filesystem).

See: https://www.kernel.org/doc/Documentation/filesystems/overlayfs.txt
"""

import contextlib
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class OverlayfsApi(recipe_api.RecipeApi):
  """A module for interacting with OverlayFS mounts."""

  def __init__(self, props, *args, **kwargs):
    """Initialize OverlayfsApi."""
    super().__init__(*args, **kwargs)
    self._cleanup_stack = [[]]
    self.random_work_path = props.random_work_path

  @property
  def _base_work_path(self):
    """Returns a Path to the base work directory for this module."""
    if self.random_work_path:
      return self.m.path.mkdtemp()
    return self.m.path.cleanup_dir / 'overlayfs'

  def _set_cache_status(self, upperdir):
    """Returns bool of whether the path contains overlay directories."""
    return self.m.path.exists(upperdir)

  def cleanup_overlay_directories(self, cache_name):
    """Remove the upper and workdiretories to reset a named cache mount.

    Resets the status of an overlayfs mount by removing both the work and
    upper directories.  This is typically used if the status of the lower
    directory changes.

    Args:
      cache_name (str): Name of the named cache to cleanup.
    """
    overlay_directories = ['upperdir', 'workdir']
    for directory in overlay_directories:
      self.m.step(
          'cleanup overlayfs %s' % directory,
          ['rm', '-rf',
           self.m.path.cache_dir.joinpath(cache_name, directory)],
          infra_step=True)

  def mount(self, name, lowerdir_path, mount_path, persist=False):
    """Mount an OverlayFS.

    As an overlay is mounted, the overlay is then added to the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      * name (str): An alphanumeric name for the mount, used for display and
          implementation details. Underscores are allowed. Should usually be
          unique within a recipe.
      * lowerdir_path (Path): Path to the OverlayFS "lowerdir". See mount(8)
          "Mount options for overlay".
      * mount_path (Path): Path to mount the OverlayFS at. Will be created if
          it doesn't exist.
      * persist (bool): Whether to persist the mount beyond one execution.
    """
    _is_valid_char = lambda char: char.isalnum() or char == '_'
    assert all(
        _is_valid_char(char) for char in name
    ), 'overlayfs mount names may only contain alphanumeric characters and underscores'
    with self.m.step.nest('mount overlay %s' % name):
      with self.m.context(infra_steps=True):
        # Create overlayfs directories.
        if persist:
          work_base = self.m.path.cache_dir
        else:
          work_base = self._base_work_path
        work_base = work_base.join(name)
        upperdir_path = work_base.join('upperdir').join(name)
        if persist:
          self.m.easy.set_properties_step(**{
              '{}_warm_cache'.format(name):
                  self._set_cache_status(upperdir_path)
          })
        self.m.file.ensure_directory('create upperdir', upperdir_path)
        workdir_path = work_base.join('workdir').join(name)
        self.m.file.ensure_directory('create workdir', workdir_path)
        self.m.file.ensure_directory('create mount path', mount_path)

        # Do mount.
        mount_options = ','.join([
            'lowerdir=%s' % lowerdir_path,
            'upperdir=%s' % upperdir_path,
            'workdir=%s' % workdir_path,
            'x-chromeos-overlay.name=%s' % name,
        ])
        self.m.step('mount', [
            'sudo', '-n', 'mount', '-t', 'overlay', '--options', mount_options,
            'overlay', mount_path
        ], infra_step=True)
        self._cleanup_mount(name, mount_path)

  def unmount(self, name, mount_path):
    """Unmount an OverlayFS.

    As an overlay is unmounted, the overlay is then removed from the stack
    that is used by the context manager to unmount as the task ends.

    Args:
      * name (str): The name used for |mount|.
      * mount_path (Path): Path to unmount the OverlayFS from.

    """
    unmount_script = self.repo_resource('recipe_scripts/umount_path.sh')
    cmd = str(unmount_script)
    try:
      self.m.step('unmount overlay %s' % name, [cmd, mount_path],
                  infra_step=True)
    except StepFailure:
      self.m.easy.set_properties_step(unmount_failure=True)

    # overlayfs leaves an empty dir called 'work', which is readable only by root.
    # But, 'workdir' needs to be empty for next mount.
    self.m.step(
        'cleanup overlayfs workdir',
        ['sudo', 'rm', '-rf',
         self.m.path.cache_dir.joinpath(name, 'workdir')], infra_step=True)

    self._cleanup_unmount(name, mount_path)

  @contextlib.contextmanager
  def cleanup_context(self):
    """Returns a context that cleans up any overlayfs mounts created in it.

    Upon exiting the context manager, each mounted overlay is then iterated
    through and unmounted.
    """
    cleanup_mounts = []
    self._cleanup_stack.append(cleanup_mounts)
    try:
      yield
    finally:
      if cleanup_mounts:
        with self.m.step.nest('clean up overlayfs mounts'):
          for name, mount_path in list(cleanup_mounts):
            self.unmount(name, mount_path)
      self._cleanup_stack.pop()

  def _cleanup_mount(self, name, mount_path):
    """Track mount for cleanup_context.

    Each mounted overlay is added to the stack to be unmounted by
    the context handler.
    """
    self._cleanup_stack[-1].append((name, mount_path))

  def _cleanup_unmount(self, name, mount_path):
    """Track unmount for cleanup_context.

    As an overlay is unmounted, the item is then removed from the stack
    to avoid attempting to unmount at a later time.
    """
    item = (name, mount_path)
    for mounts in reversed(self._cleanup_stack):
      if item in mounts:
        mounts.remove(item)
        break
    else:
      # Unmount succeeded, so just warn that something odd has happened.
      self.m.step.active_result.presentation.step_text += (
          '<br/>[WARNING: overlayfs unmount bookkeeping error for %s]' % name)
