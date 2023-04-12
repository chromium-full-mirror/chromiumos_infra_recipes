# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'vmlab',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  # Lease VM
  api.vmlab.lease_vm('vmlab-config', 'vm-image')
  api.vmlab.lease_vm('vmlab-config', 'vm-image', swarming_bot_name='bot-name')

  # Import VM image
  api.vmlab.import_image('build-path', True)
  api.vmlab.import_image('build-path', False)
  api.vmlab.import_image('build-path', True, assert_ready=True)

  # Clean up VM images
  api.vmlab.clean_images(True, 1)
  api.vmlab.clean_images(False, 1)

  # Stub
  api.vmlab.delete_vm('vmlab-config', 'instance-name')
  api.vmlab.cleanup_vm('vmlab-config', swarming_bot_name='bot-name')
  api.vmlab.cleanup_vm('vmlab-config', swarming_bot_name='bot-name',
                       allow_failure=False)
  api.vmlab.cleanup_vm('vmlab-config', swarming_bot_name='bot-name',
                       allow_failure=True)
  api.vmlab.cleanup_vm('vmlab-config', swarming_bot_name='bot-name',
                       dry_run=True)


def GenTests(api):
  yield api.test('basic')
  yield api.test(
      'cleanup failure ignored',
      api.step_data('cleanup vm (3).call `vmlab`.run cmd', retcode=1))
  yield api.test(
      'cleanup failure raise',
      api.step_data('cleanup vm (2).call `vmlab`.run cmd', retcode=1),
      status='FAILURE')
  yield api.test(
      'import not ready',
      api.step_data('import VM image (3).call `vmlab`.run cmd',
                    stdout=api.raw_io.output_text('{"status": "PENDING"}\n')),
      api.post_check(post_process.StepFailure, 'import VM image (3)'),
      status='FAILURE')
