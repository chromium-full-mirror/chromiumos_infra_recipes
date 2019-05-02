# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

import os

from recipe_engine import recipe_api

from PB.chromiumos import common


class CrosSdkApi(recipe_api.RecipeApi):
  """A module for interacting with cros_sdk."""

  def initialize(self):
    """Initialize CrosSdkApi."""
    self.configure(self.m.path['cache'].join('cros_sdk'))

  def configure(self, chroot_parent_path):
    """Configure CrosSdkApi.

    Args:
      chroot_parent_path (Path): Parent for chroot directory.
    """
    with self.m.step.nest('configure chroot path'):
      self._chroot_path = chroot_parent_path.join('chroot')
      self.m.file.ensure_directory('ensure chroot path', self._chroot_path)
      # TODO(crbug.com/949721): Currently, chromite depends on the chroot living
      # within the source tree. As a workaround, link the external chroot to
      # both source trees to make it look legit. New chromite services should
      # accept the chroot path as a parameter.
      self._link_chroot(self.m.cros_source.workspace_path)
      self._link_chroot(self.m.cros_source.master_path)

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.repo_resource('cros_sdk')

  @property
  def chroot(self):
    """Return a chromiumos.common.Chroot."""
    return common.Chroot(path=str(self._chroot_path))

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
        self._chroot_path,
    ]

    cmd += args
    return self.m.step(name, cmd, **kwargs)

  def _link_chroot(self, checkout_path):
    """Link the chroot to a chromiumos checkout.

    Args:
      checkout_path (Path): Path to the checkout root.
    """
    checkout_basename = self.m.path.basename(checkout_path)
    self.m.file.ensure_directory('ensure %s' % checkout_basename, checkout_path)

    chroot_link = checkout_path.join('chroot')
    if self.m.path.exists(chroot_link):
      self.m.file.remove('remove original chroot link', chroot_link)

    self.m.file.symlink('link %s to chroot' % checkout_basename,
                        self._chroot_path, chroot_link)

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
