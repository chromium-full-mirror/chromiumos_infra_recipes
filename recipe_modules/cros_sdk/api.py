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

  def __call__(self, name, args, chroot_path=None, **kwargs):
    """Executes 'cros_sdk' with the supplied arguments.

    Args:
      * name (str): The name of the step.
      * args (list): A list of arguments to supply to 'cros_sdk'.
      * chroot_path (str|Path): Path to the chroot. Defaults to a cache dir.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      See 'step.__call__'.
    """
    if chroot_path is None:
      chroot_path = self.m.path['cache'].join('cros_chroot')
    cmd = [self.cros_sdk_path, '--nouse-image', '--chroot', chroot_path] + args
    return self.m.step(name, cmd, **kwargs)

  def run(self, cmd, env=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

    Args:
      * cmd (list): A command and arguments to run.
      * env (dict): A dict of environment variables to pass to the command.
      * kwargs: Keyword arguments to pass to __call__.

    Returns:
      See 'step.__call__'.
    """
    name = '(cros_sdk) %s' % cmd[0]
    args = []
    if env is not None:
      args += ['%s=%s' % x for x in env.items()]
    args += ['--'] + cmd
    return self(name, args, **kwargs)
