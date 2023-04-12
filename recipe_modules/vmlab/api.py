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

  def import_image(self, build_path, wait, assert_ready=False):
    """Import a VM image from GCS to GCE.

    Args:
      build_path: build path of the image in GCS without bucket, for example
                  betty-arc-r-cq/R108-15164.0.0-71927-8801111609984657185
      wait: whether to wait for the image import to complete.
      assert_ready: raise StepFailure if image is not in READY state.

    Returns:
      Object containing project, name, status, source of the imported image.
    """
    with self.m.step.nest("import VM image"):
      args = ["-build-path", build_path, '-json']
      if wait:
        args.append('-wait')
      result = self._run(
          ["image"] + args,
          test_data='{"project":"p", "name":"n", "status":"READY", "source":"s"}\n'
      )
      result_json = json.loads(result.strip())
      if assert_ready and result_json['status'] != 'READY':
        raise recipe_api.StepFailure("Image is not ready.")
      return result_json

  def clean_images(self, dry_run, rate=1):
    """Clean up VM images in the GCP project.

    Remove expired images, return error if there is any unknown image.

    Args:
      dry_run: don't really delete images if true.
      rate: maximum number of requests per second.

    Returns:
      Object containing the result of the clean up. Includes total number of
        images, deleted images, failed to import images, unknown images.
    """
    with self.m.step.nest("clean up images"):
      args = ["-rate", str(rate), "-json"]
      if dry_run:
        args.append('-dry-run')
      result = self._run(
          ["clean-images"] + args,
          test_data='{"Total":2,"Deleted":["d"],"Failed":[],"Unknown":[]}\n')
      return json.loads(result.strip())

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
      result = self._run(
          ["lease"] + args,
          test_data='{"name":"prefix-b310d29ece80d77ab4f4ffac8", "ssh":{"address":"8.8.8.8", "port":22}}\n'
      )
      return json.loads(result.strip())

  def cleanup_vm(self, config, swarming_bot_name, dry_run=False, rate=1,
                 allow_failure=False):
    """Cleanup orphan VM instances.

    Args:
      config: config name preconfigured in vmlab CLI.
      swarming_bot_name: only cleanup instances created by given swarming bot.
      dry_run: dry run mode. only list, but not delete any instance.
      rate: rate limit for deleting instance requests.
      allow_failure: if set to True, step will not raise if CLI returns non-zero result.
    """
    with self.m.step.nest('cleanup vm') as presentation:
      args = []
      assert len(swarming_bot_name) > 0, 'swarming_bot_name must be set'
      args.extend(['--swarming-bot-name', swarming_bot_name])
      args.extend(['-rate', str(rate)])
      if dry_run:
        args.append('-dry-run')
      try:
        result = self._run(['cleanup-instances', '--config', config] + args,
                           test_data='{}\n')
      except recipe_api.StepFailure as e:
        if allow_failure:
          presentation.status = self.m.step.FAILURE
          return {}
        raise e
    return json.loads(result.strip())

  def delete_vm(self, config, name):
    """Deletes a given VM instance.

    Args:
      config: config name presentation in vmlab CLI.
      name: name of the instnace returned by lease_vm.
    """
    with self.m.step.nest('delete vm'):
      args = ["--config", config, "--instance-name", name]
      self._run(["release"] + args, test_data='')
