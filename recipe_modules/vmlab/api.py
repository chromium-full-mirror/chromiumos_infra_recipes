# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_api

DEFAULT_IMAGE_PROJECT = 'betty-cloud-prototype'


class VmlabApi(recipe_api.RecipeApi):
  """A module to interact with Chrome OS VMLab."""

  def __init__(self, properties, *args, **kwargs):
    """Initialize GcloudApi."""
    super().__init__(*args, **kwargs)
    self._properties = properties
    self._cmd = None

  def _ensure_vmlab(self):
    """Ensures vmlab cipd package is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure vmlab'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'vmlab')
        pkgs = self.m.cipd.EnsureFile()
        # TODO(fqj): Switch to other label. We don't have any other tags yet,
        # use latest for now temporarily.
        pkgs.add_package('chromiumos/infra/vmlab/${platform}', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('vmlab')

  def _run(self, arguments, test_data=''):
    """Installs vmlab and run commands.

    Args:
      arguments: subcommands and parameters for vmlab CLI.
    """
    self._ensure_vmlab()
    with self.m.step.nest('call `vmlab`') as presentation:
      stdout = self.m.step(
          'run cmd', [self._cmd] + arguments,
          stdout=self.m.raw_io.output_text(),
          step_test_data=(lambda: self.m.raw_io.test_api.stream_output_text(
              test_data))).stdout
      presentation.logs['vmlab CLI output'] = stdout
    return stdout

  def import_image(self):
    pass

  def lease_vm(self, config, image_name, image_project=DEFAULT_IMAGE_PROJECT,
               swarming_bot_name=None):
    """Lease a VM.

    Args:
      config: config name preconfigured in vmlab CLI.
      image_name: name of the image to use.
      image_project: GCP project where the image is stored.
      swarming_bot_name: name of the sarming bot. cleanup_vm may not work well
    if empty swarming_bot_name is provided at some backend.
    """
    with self.m.step.nest("lease vm"):
      args = [
          "--config", config, "--gce-image-name", image_name,
          "--gce-image-project", image_project, '--json'
      ]
      if swarming_bot_name:
        args.extend(["--swarming-bot-name", swarming_bot_name])
      # TODO(fqj): provide correct test data.
      result = self._run(["lease"] + args, test_data='{}\n')
      return json.loads(result.strip())

  def cleanup_vm(self):
    pass

  def delete_vm(self):
    pass
