# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with cros_test chromite api."""

from recipe_engine import recipe_api

class CrosTestApi(recipe_api.RecipeApi):
  @property
  def _ws_path(self):
    """Returns a Path to be mounted as a cros_sdk workspace."""
    return self.m.path['cleanup'].join('cros_test')

  @property
  def image_path(self):
    """Returns a Path to image artifacts."""
    return self._ws_path.join('image')

  def run_vm_test(self, build_target, test_suite):
    """Run the specified test in a vm.

    Expects chromiumos_qemu_image.bin and id_rsa to be present in image_path.

    Args:
      build_target (str): The build target to test against.
      test_suite (str): A valid Autotest vm test suite.
    """
    # TODO(yshaul): replace test_that with lucifer
    cmd = [
        'cros_run_vm_test', '--debug', '--board=%s' % build_target,
        '--image-path', '/mnt/host/workspace/image/chromiumos_qemu_image.bin',
        '--private-key', '/mnt/host/workspace/image/id_rsa',
        '--results-dir', '/mnt/host/workspace/results',
        '--ssh-port', self._find_free_port(),
        '--autotest', test_suite,
        # The following must be a single arg, else the flag parser thinks
        # --test_that-args and --whitelist-chrome-crashes
        # are two separate flags.
        '--test_that-args=--whitelist-chrome-crashes'
    ]
    self.m.cros_sdk.run('run vm test suite %s' % test_suite, cmd,
                        workspace=self._ws_path)

  def _find_free_port(self):
    test_port = self.m.raw_io.test_api.stream_output('9228')
    step_result = self.m.python('find free port', 
                                self.resource('find_free_port.py'),
                                stdout=self.m.raw_io.output(),
                                step_test_data=lambda: test_port)

    return step_result.stdout
