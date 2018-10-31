# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Steps for calling cros_sdk."""

from recipe_engine import recipe_api


class CrosSdkApi(recipe_api.RecipeApi):
  """Provides steps for cros_sdk operations."""

  @property
  def cros_sdk_path(self):
    return self.m.depot_tools.package_repo_resource('cros_sdk')

  def __call__(self, args, name=None, **kwargs):
    """Executes 'cros_sdk' with the supplied arguments.

    Args:
      * args (list): A list of arguments to supply to 'cros_sdk'.
      * name (str): The name of the step. If None, generate from the args.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      See 'step.__call__'.
    """
    if name is None:
      name = 'cros_sdk %s' % ' '.join(args)
    return self.m.step(name, [self.cros_sdk_path] + args, **kwargs)

  def run(self, cmd, env=None, **kwargs):
    """Runs a command in a cros_sdk chroot.

    Args:
      * cmd (list): A command and arguments to run.
      * env (dict): A dict of environment variables to pass to the command.
      * kwargs: Keyword arguments to pass to __call__.

    Returns:
      See 'step.__call__'.
    """
    if 'name' not in kwargs:
      kwargs['name'] = '(cros_sdk) %s' % cmd[0]
    args = []
    if env is not None:
      args += ['%s=%s' % x for x in env.items()]
    args += ['--'] + cmd
    return self(args, **kwargs)
