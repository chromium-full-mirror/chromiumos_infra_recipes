# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.test_platform.skylab_local_state import load
from PB.test_platform.phosphorus.fetchcrashes import FetchCrashesRequest
from PB.test_platform.phosphorus.prejob import PrejobRequest
from PB.test_platform.phosphorus.runtest import RunTestRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSRequest
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest
from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'phosphorus',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


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
    api.phosphorus.parse('')

  api.phosphorus.read_dut_hostname()

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.save_skylab_local_state('foo-state', 'dummy-dut1',
                                           ['dummy-dut2'])
  with api.assertions.assertRaises(ValueError):
    api.phosphorus.save_and_seal_skylab_local_state('bar-state', 'dummy-dut1',
                                                    ['dummy-dut2'])
  api.phosphorus.load_skylab_local_state('test-id')
  api.phosphorus.save_skylab_local_state('baz-state', 'dummy-dut1',
                                         ['dummy-dut2'])
  api.phosphorus.save_and_seal_skylab_local_state('qux-state', 'dummy-dut1',
                                                  ['dummy-dut2'])
  api.phosphorus.remove_autotest_results_dir()
  _ = api.phosphorus.parse('/path/to/results')


def GenTests(api):
  yield api.test(
      'basic',
      api.phosphorus.properties(dut_name='placeholder'),
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(results_dir='placeholder-results-dir')))),
  )
  yield (api.test(
      'with-bot-prefix',
      api.phosphorus.properties(dut_name='placeholder',
                                bot_prefix='someprefix'),
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(results_dir='placeholder-results-dir')))),
  ) + api.post_process(DropExpectation))
  yield (api.test(
      'cros-host-with-bot-prefix',
      api.phosphorus.properties(dut_name='cros-chromeos1-row2-rack3-host4'),
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(results_dir='placeholder-results-dir')))),
  ) + api.post_process(DropExpectation))
  yield (api.test(
      'host-without-valid-bot-prefix',
      api.phosphorus.properties(dut_name='noprefix-chromeos1-row2-rack3-host4'),
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(results_dir='placeholder-results-dir')))),
  ) + api.post_process(DropExpectation))
  yield (api.test(
      'cloudbots-dut-host-bot',
      api.phosphorus.properties(dut_name='cloudbots-prod-placeholder-asdf'),
      api.step_data(
          'call `phosphorus` (12).load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(results_dir='placeholder-results-dir')))),
  ))
