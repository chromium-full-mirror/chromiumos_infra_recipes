# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'phosphorus',
]

from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusEnvProperties
from PB.test_platform import skylab_local_state
from PB.test_platform.phosphorus.fetchcrashes import FetchCrashesRequest
from PB.test_platform.phosphorus.prejob import PrejobRequest
from PB.test_platform.phosphorus.runtest import RunTestRequest
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSRequest

from google.protobuf import json_format


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.phosphorus.prejob(None)
  prejob_req = PrejobRequest()
  api.phosphorus.prejob(prejob_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.run_test(None)
  run_test_req = RunTestRequest()
  api.phosphorus.run_test(run_test_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.fetch_crashes(None)
  fetch_crashes_req = FetchCrashesRequest()
  api.phosphorus.fetch_crashes(fetch_crashes_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.upload_to_gs(None)
  upload_to_gs_req = UploadToGSRequest()
  api.phosphorus.upload_to_gs(upload_to_gs_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.upload_to_tko(None)
  upload_to_tko_req = UploadToTkoRequest()
  api.phosphorus.upload_to_tko(upload_to_tko_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.parse("")

  api.phosphorus.read_dut_hostname()

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.save_skylab_local_state('foo-state')
  with api.assertions.assertRaises(ValueError):
    api.phosphorus.save_and_seal_skylab_local_state('bar-state')
  api.phosphorus.load_skylab_local_state('test-id')
  api.phosphorus.save_skylab_local_state('baz-state')
  api.phosphorus.save_and_seal_skylab_local_state('qux-state')
  _ = api.phosphorus.parse("/path/to/results")


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/phosphorus':
                  PhosphorusProperties(
                      version=PhosphorusProperties.Version(
                          cipd_label='some-cipd-label',
                      ), config={
                          'admin_service': 'foo-service',
                          'cros_inventory_service': 'inv-service',
                          'cros_ufs_service': 'ufs-service',
                          'autotest_dir': '/path/to/autotest',
                      }),
          }) + api.properties.environ(
              PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                      SWARMING_TASK_ID='dummy-task-id',
                                      SKYLAB_DUT_ID='dummy-dut-id')) +
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                      results_dir='dummy-results-dir')))),
  )
