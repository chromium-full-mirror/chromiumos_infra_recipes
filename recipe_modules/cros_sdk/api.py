# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_sdk, the interface to the CrOS SDK."""

from recipe_engine import recipe_api


class CrosSdkApi(recipe_api.RecipeApi):
  """A module for interacting with cros_sdk."""

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.package_repo_resource('cros_sdk')

  def __call__(self, name, chroot_path, args, **kwargs):
    """Executes 'cros_sdk' with the supplied arguments.

    Args:
      * name (str): The name of the step.
      * chroot_path (str|Path): Path to the chroot.
      * args (list): A list of arguments to supply to 'cros_sdk'.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      See 'step.__call__'.
    """
    cmd = [self.cros_sdk_path, '--nouse-image', '--chroot', chroot_path] + args
    return self.m.step(name, cmd, **kwargs)

  def run(self, name, chroot_path, cmd, env=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

    Args:
      * name (str): The name of the step.
      * chroot_path (str|Path): Path to the chroot.
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
    return self(name, chroot_path, args, **kwargs)
