# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with OverlayFS mounts (the Linux 'overlay' filesystem).

See: https://www.kernel.org/doc/Documentation/filesystems/overlayfs.txt
"""

import collections
import contextlib
import tempfile

from recipe_engine import config_types
from recipe_engine import recipe_api


class OverlayfsApi(recipe_api.RecipeApi):
  """A module for interacting with OverlayFS mounts."""

  def __init__(self, *args, **kwargs):
    """Initialize OverlayfsApi."""
    super(OverlayfsApi, self).__init__(*args, **kwargs)
    self._cleanup_stack = [[]]

  @property
  def _base_work_path(self):
    """Returns a Path to the base work directory for this module."""
    return self.m.path['cleanup'].join('overlayfs')

  @property
  def _persist_work_path(self):
    """Returns a Path to the persisted work directory for this module."""
    return self.m.path['cache'].join('chromiumos')

  def mount(self, name, lowerdir_path, mount_path, persist=False):
    """Mount an OverlayFS.

    Args:
      * name (str): An alphanumeric name for the mount, used for display and
          implementation details. Should usually be unique within a recipe.
      * lowerdir_path (Path): Path to the OverlayFS "lowerdir". See mount(8)
          "Mount options for overlay".
      * mount_path (Path): Path to mount the OverlayFS at. Will be created if
          it doesn't exist.
      * persist (bool): Whether to persist the mount beyond one execution.
    """
    assert name.isalnum(), 'overlayfs mount names must be alphanumeric'
    with self.m.step.nest('mount overlay %s' % name):
      with self.m.context(infra_steps=True):
        # Create overlayfs directories.
        if persist:
          work_base = self._persist_work_path
        else:
          work_base = self._base_work_path
        upperdir_path = work_base.join('upperdir').join(name)
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

    Args:
      * name (str): The name used for |mount|.
      * mount_path (Path): Path to unmount the OverlayFS from.

    """
    self.m.step('unmount overlay %s' % name, ['sudo', 'umount', mount_path],
                infra_step=True)

    self._cleanup_unmount(name, mount_path)

  @contextlib.contextmanager
  def cleanup_context(self):
    """Returns a context that cleans up any overlayfs mounts created in it."""
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
    """Track mount for cleanup_context."""
    self._cleanup_stack[-1].append((name, mount_path))

  def _cleanup_unmount(self, name, mount_path):
    """Track unmount for cleanup_context."""
    item = (name, mount_path)
    for mounts in reversed(self._cleanup_stack):
      if item in mounts:
        mounts.remove(item)
        break
    else:
      # Unmount succeeded, so just warn that something odd has happened.
      self.m.step.active_result.presentation.step_text += (
          '<br/>[WARNING: overlayfs unmount bookkeeping error for %s]' % name)
