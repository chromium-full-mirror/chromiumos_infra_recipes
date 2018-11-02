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

  @property
  def base_work_path(self):
    """Returns a Path to the base work directory for this module."""
    return self.m.path['cleanup'].join('overlayfs')

  def mount(self, name, lowerdir_path, mount_path):
    """Mount an OverlayFS.

    Args:
      * name (str): An alphanumeric name for the mount, used for display and
          implementation details. Should usually be unique within a recipe.
      * lowerdir_path (Path): Path to the OverlayFS "lowerdir". See mount(8)
          "Mount options for overlay".
      * mount_path (Path): Path to mount the OverlayFS at. Will be created if
          it doesn't exist.

    """
    assert name.isalnum()
    with self.m.context(name_prefix='mount overlay %s' % name,
                        increment_nest_level=True, infra_steps=True):
      # Create overlayfs directories.
      work_base = self.base_work_path
      upperdir_path = work_base.join('upperdir')
      self.m.file.ensure_directory('create upperdir', upperdir_path)
      workdir_path = work_base.join('workdir')
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
      ])

  def unmount(self, name, mount_path):
    """Unmount an OverlayFS.

    Args:
      * mount_path (Path): Path to unmount the OverlayFS from.

    """
    self.m.step('unmount overlay %s' % name, ['sudo', 'umount', mount_path],
                infra_step=True)

  @contextlib.contextmanager
  def context(self, name, lowerdir_path, mount_path):
    """Return a context in a mounted OverlayFS.

    The returned context will see a mounted OverlayFS as with 'mount', with the
    cwd set to the mount_path. The OverlayFS will be unmounted when the context
    exits.

    Args:
      * name (str): An alphanumeric name for the mount, used for display and
          implementation details. Should usually be unique within a recipe.
      * lowerdir_path (Path): Path to the OverlayFS "lowerdir". See mount(8)
          "Mount options for overlay".
      * mount_path (Path): Path to mount the OverlayFS at. Will be created if
          it doesn't exist.

    """
    self.mount(name, lowerdir_path, mount_path)
    try:
      with self.m.context(cwd=mount_path):
        yield
    finally:
      self.unmount(name, mount_path)
