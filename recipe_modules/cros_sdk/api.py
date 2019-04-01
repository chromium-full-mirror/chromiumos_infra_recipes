# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

import os

from recipe_engine import recipe_api

# The path within the chroot where the workspace directory is mounted.
CHROOT_WORKSPACE_PATH = '/mnt/host/workspace'


class CrosSdkApi(recipe_api.RecipeApi):
  """A module for interacting with cros_sdk."""

  def initialize(self):
    """Initialize CrosSdkApi."""
    self.configure(self.m.path['start_dir'].join('cros_sdk'))

  def configure(self, chroot_parent_path, chrome_root=None):
    """Configure CrosSdkApi.

    Args:
      chroot_parent_path (Path): Parent for chroot directory.
      chrome_root (Path): Path containing a Chrome checkout, which will be
       mounted into the chroot. If None, no Chrome checkout will be mounted.
    """
    self._chroot_path = chroot_parent_path.join('chroot')
    self._chrome_root = chrome_root

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.repo_resource('cros_sdk')

  @property
  def chroot_path(self):
    return self._chroot_path

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
        '--nouse-image',
        '--chroot',
        self.chroot_path,
    ]

    if self._chrome_root:
      cmd += ['--chrome_root', self._chrome_root]

    cmd += args
    return self.m.step(name, cmd, **kwargs)

  def run(self, name, cmd, env=None, workspace=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

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
    if workspace is not None:
      args += ['--workspace', workspace]
    args += ['--'] + cmd
    return self(name, args, **kwargs)

  def workspace_path_to_chroot(self, workspace_root, workspace_path):
    """Translate a workspace path to its mounted chroot equivalent.

    Args:
      * workspace_root (Path): The path to be passed to cros_sdk --workspace.
      * workspace_path (Path): A child of |workspace_root|, to be translated.

    Returns:
      str: The translated path, which will be valid within the cros_sdk chroot.
    """
    assert workspace_root.is_parent_of(workspace_path), \
      'workspace path not in root'
    relpath = os.path.relpath(str(workspace_path), str(workspace_root))
    return os.path.join(CHROOT_WORKSPACE_PATH, relpath)
