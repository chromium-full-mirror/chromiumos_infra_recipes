# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from PB.recipe_modules.chromeos.phosphorus.phosphorus import PhosphorusEnvProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import PhosphorusProperties
from PB.recipe_modules.chromeos.service_version.service_version import ServiceVersionProperties
from PB.recipes.chromeos.test_platform.dut_leaser import DutLeaserProperties
from PB.test_platform import service_version
from PB.test_platform.skylab_local_state import load
from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'phosphorus',
    'service_version',
]


PROPERTIES = DutLeaserProperties

_DUT_STATE_NEEDS_REPAIR = 'needs_repair'

_DUT_LEASER_TEST_ID = 'dut-leaser'


def RunSteps(api, properties):
  lease_end_seconds = api.time.time() + 60 * properties.lease_length_minutes
  api.service_version.validate_service_version_if_exists()
  with api.step.nest('lease DUT for %s hr %s min' %
                     (properties.lease_length_minutes // 60,
                      properties.lease_length_minutes % 60)):
    with api.step.nest('update DUT state to %s' % _DUT_STATE_NEEDS_REPAIR):
      # Load the local state to set the results directory to save to.
      load_response = api.phosphorus.load_skylab_local_state(
          _DUT_LEASER_TEST_ID)
      api.phosphorus.save_and_seal_skylab_local_state(
          dut_state=_DUT_STATE_NEEDS_REPAIR,
          dut_name=load_response.dut_topology[0].hostname,
          peer_duts=[dut.hostname for dut in load_response.dut_topology[1:]])

    with api.step.nest('sleep for remainder of lease'):
      remaining_seconds = int(lease_end_seconds - api.time.time())
      api.time.sleep(remaining_seconds)


def GenTests(api):
  yield api.test(
      'basic',
      api.time.seed(4321),
      api.properties(
          DutLeaserProperties(
              lease_length_minutes=123,
          ), **{
              '$chromeos/phosphorus':
                  PhosphorusProperties(
                      version=PhosphorusProperties.Version(
                          cipd_label='phosphorus_prod'), config={
                              'admin_service': 'foo-service',
                              'cros_inventory_service': 'inv-service',
                              'cros_ufs_service': 'ufs-service',
                              'autotest_dir': '/path/to/autotest',
                          }),
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(crosfleet_tool=4),
                  ),
          }) +  #
      api.properties.environ(
          PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                  SWARMING_TASK_ID='dummy-task-id',
                                  SKYLAB_DUT_ID='dummy-dut-id')),
      api.step_data(
          'lease DUT for 2 hr 3 min.update DUT state to needs_repair.call `phosphorus`.load',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(
                      results_dir='dummy-results-dir',
                      dut_topology=[load.Dut(hostname='dummy-hostname')])))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'invalid-service-version',
      api.properties(
          DutLeaserProperties(
              lease_length_minutes=123,
          ), **{
              '$chromeos/phosphorus':
                  PhosphorusProperties(
                      version=PhosphorusProperties.Version(
                          cipd_label='phosphorus_prod'), config={
                              'admin_service': 'foo-service',
                              'cros_inventory_service': 'inv-service',
                              'cros_ufs_service': 'ufs-service',
                              'autotest_dir': '/path/to/autotest',
                          }),
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(crosfleet_tool=3),
                  ),
          }) +  #
      api.properties.environ(
          PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                  SWARMING_TASK_ID='dummy-task-id',
                                  SKYLAB_DUT_ID='dummy-dut-id')),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
