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
    """Cache the chroot path."""
    self.configure(self.m.path['cache'])

  def configure(self, chroot_parent_path):
    """Configure CrosSdkApi.

    Args:
      chroot_parent_path (Path): Parent for chroot directory.
    """
    with self.m.step.nest('configure chroot path'):
      self._chroot_path = chroot_parent_path.join('cros_chroot')
      self.m.file.ensure_directory('ensure chroot directory', self._chroot_path)
      self._chrome_root = None
      self._goma_dir = None
      self._goma_client_json = None
      self._use_flags = None

  @property
  def cros_sdk_path(self):
    """Returns a Path to the cros_sdk script."""
    return self.m.depot_tools.repo_resource('cros_sdk')

  @property
  def chroot(self):
    """Return a chromiumos.common.Chroot."""
    env = None
    if self._use_flags:
      env = common.Chroot.ChrootEnv(
          use_flags=self._use_flags
      )
    goma_config = None
    if self.has_goma_config():
      goma_config = common.GomaConfig(
          goma_dir=str(self._goma_dir),
          goma_client_json=str(self._goma_client_json),
      )
    return common.Chroot(
        path=str(self._chroot_path),
        chrome_dir=self._chrome_root,
        env=env,
        goma=goma_config,
    )

  def set_chrome_root(self, chrome_root):
    self._chrome_root = chrome_root

  def set_goma_config(self, goma_dir, goma_client_json):
    self._goma_dir = goma_dir
    self._goma_client_json = goma_client_json

  def has_goma_config(self):
    return bool(self._goma_dir and self._goma_client_json)

  def set_use_flags(self, use_flags):
    self._use_flags = use_flags

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

  def link_chroot(self, checkout_path):
    """Link the chroot to a chromiumos checkout.

    Args:
      checkout_path (Path): Path to the checkout root.
    """
    checkout_basename = self.m.path.basename(checkout_path)
    with self.m.step.nest('link chroot in %s' % checkout_basename):
      self.m.file.ensure_directory('ensure %s' % checkout_basename,
                                   checkout_path)

      chroot_link = checkout_path.join('chroot')
      if self.m.path.exists(chroot_link):
        self.m.file.remove('remove original chroot link', chroot_link)

      self.m.file.symlink('link %s to chroot' % checkout_basename,
                          self._chroot_path, chroot_link)

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

  def chmod_chroot(self, checkout_path):
    """Chroot is deployed as root, therfore change permissions to
       allow for Swarming cache uninstall/install.

    Args:
      checkout_path (Path): Path to the checkout root.
    """
    if self.m.path.exists(self._chroot_path):
      chmod_cmd = ['sudo', '-n', 'chmod', 'a+rwX,-t', self._chroot_path]
      self.m.step('changing permissions of %s' % self._chroot_path, chmod_cmd,
                  infra_step=True)

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
