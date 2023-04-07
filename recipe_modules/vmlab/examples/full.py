# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'vmlab',
]


def RunSteps(api):
  # Lease VM
  api.vmlab.lease_vm('vmlab-config', 'vm-image')
  api.vmlab.lease_vm('vmlab-config', 'vm-image', swarming_bot_name='bot-name')

  # Import VM image
  api.vmlab.import_image('build-path', True)
  api.vmlab.import_image('build-path', False)

  # Clean up VM images
  api.vmlab.clean_images(True, 1)
  api.vmlab.clean_images(False, 1)

  # Stub
  api.vmlab.delete_vm()
  api.vmlab.cleanup_vm()


def GenTests(api):
  yield api.test('basic')
