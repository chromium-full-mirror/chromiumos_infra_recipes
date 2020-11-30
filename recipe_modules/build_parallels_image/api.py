# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class BuildParallelsImageCommand(recipe_api.RecipeApi):
  """Module for issuing build-parallels-image commands.

  This module should only be used on lab drones, where SWARMING_BOT_ID
  is set.
  """

  def __init__(self, env_properties, **kwargs):
    super(BuildParallelsImageCommand, self).__init__(**kwargs)
    self._cmd = None
    self._bot_id = env_properties.SWARMING_BOT_ID

  def _run(self, subcommand, args):
    """Generic subcommand runner for build-parallels-image.

    Args:
      subcommand (str): subcommand to run
      args (List[str]): the arguments to pass to the subcommand
    """
    with self.m.step.nest('call `build-parallels-image`'):
      self._ensure_build_parallels_image()
      cmd = [
          self._cmd,
          subcommand,
      ] + args
      return self.m.step(subcommand, cmd)

  def provision(self, image_gs_path):
    """Provisions the given Chrome OS image onto the attached DUT.

    The provisioned image will include the pita DLC.

    Args:
      image_gs_path (str): the Google Storage path to where kernel,
        rootfs and stateful images are located. For example,
        'gs://chromeos-image-archive/eve-release/R86-13380.0.0'.
    """
    return self._run(
        'provision',
        ['--dut_name', self.dut_name, '--image_gs_path', image_gs_path])

  def _ensure_build_parallels_image(self):
    """Ensure the build-parallels-image CLI is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure build-parallels-image'):
        cipd_dir = self.m.path['start_dir'].join('cipd',
                                                 'build-parallels-image')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/build-parallels-image/${platform}',
                         'prod')
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('build-parallels-image')

  @property
  def dut_name(self):
    """Returns the DUT resource name."""
    return _dut_name_from_bot_id(self._bot_id)


def _dut_name_from_bot_id(bot_id):
  """Extract the DUT name from the SWARMING_BOT_ID environment variable.

  Args:
    bot_id (str): The value of the SWARMING_BOT_ID environment variable.

  Returns:
    dut_name (str): The resource name of the DUT.
  """
  # This same 'crossk-' check is used elsewhere in recipes, so if you have
  # reason to change it here, please search the code and update the other
  # references too.
  expected_prefix = 'crossk-'
  if not bot_id.startswith(expected_prefix):
    raise ValueError(
        'SWARMING_BOT_ID does not start with expected prefix {}, got {}'.format(
            expected_prefix, bot_id))
  return bot_id[len(expected_prefix):]
