# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

from PB.chromite.api.firmware import (BuildAllTotFirmwareRequest,
                                      TestAllTotFirmwareRequest)
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties

PROPERTIES = BuildFirmwareProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    api.cros_build_api.FirmwareService.BuildAllTotFirmware(
        BuildAllTotFirmwareRequest(
            chroot=api.cros_sdk.chroot,
            firmware_location=properties.firmware_location),
        name='build firmware')
    api.cros_build_api.FirmwareService.TestAllTotFirmware(
        TestAllTotFirmwareRequest(
            chroot=api.cros_sdk.chroot,
            firmware_location=properties.firmware_location),
        name='test firmware')


def GenTests(api):

  def test(name, **kwargs):
    kwargs.setdefault('input_properties', dict(firmware_location=1))
    return api.test(name, api.test_util.test_child_build(None, **kwargs).build)

  yield test('postsubmit', builder='fw-ec-postsubmit')

  yield test('cq', cq=True, builder='fw-ec-cq')
