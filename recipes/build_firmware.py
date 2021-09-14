# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.firmware import (BuildAllFirmwareRequest,
                                      TestAllFirmwareRequest)
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties

PROPERTIES = BuildFirmwareProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    service = api.cros_build_api.FirmwareService
    chroot = api.cros_sdk.chroot
    location = properties.firmware_location or config.general.firmware_location
    service.BuildAllFirmware(
        BuildAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                code_coverage=properties.code_coverage),
        name='build firmware')
    service.TestAllFirmware(
        TestAllFirmwareRequest(firmware_location=location, chroot=chroot,
                               code_coverage=properties.code_coverage),
        name='test firmware')
    if properties.working_artifacts:
      api.build_menu.upload_artifacts(config=config, failing_build=False)
    else:
      # TODO(b/177907749): Once we have artifacts in all of the builders, stop
      # ignoring failures.
      with api.step.nest('try to upload artifacts') as pres:
        try:
          api.build_menu.upload_artifacts(config=config, failing_build=False)
        except StepFailure as ex:
          pres.step_text = ex.reason_message()


def GenTests(api):

  def test(name, *args, **kwargs):
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', dict(firmware_location=1))
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args)

  yield test('postsubmit')

  yield test('cq', cq=True, builder='fw-ec-cq')

  yield test(
      'upload_fail',
      api.cros_build_api.set_api_return(
          'try to upload artifacts.upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts', retcode=1),
      api.post_check(post_process.StatusSuccess))

  yield test(
      'working_upload_fail',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1), api.post_check(post_process.StatusAnyFailure),
      input_properties=(dict(firmware_location=1, working_artifacts=True)))
