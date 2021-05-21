# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket', 'recipe_engine/context',
    'recipe_engine/properties', 'recipe_engine/raw_io', 'recipe_engine/step',
    'recipe_engine/time', 'recipe_engine/uuid', 'dut_interface', 'phosphorus'
]

from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusEnvProperties
from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties

PROPERTIES = TestRunnerProperties


def RunSteps(api, properties):
  api.dut_interface.create(api, properties)


def GenTests(api):

  def _misc_properties():
    return (api.properties(
        TestRunnerProperties(
            config={
                'lab': {
                    'admin_service': 'foo-service',
                    'cros_inventory_service': 'inv-service',
                    'cros_ufs_service': 'ufs-service'
                },
                'harness': {
                    'autotest_dir': '/path/to/autotest',
                    'prejob_deadline_seconds': 60 * 60,
                },
                'output': {
                    'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                },
                'result_flow_pubsub': {
                    'project': 'foo-proj',
                    'topic': 'foo-topic',
                },
            }), **{
                '$chromeos/phosphorus':
                    PhosphorusProperties(
                        version=PhosphorusProperties.Version(
                            cipd_label='phosphorus_prod'), config={
                                'admin_service': 'foo-service',
                                'cros_inventory_service': 'inv-service',
                                'cros_ufs_service': 'ufs-service',
                                'autotest_dir': '/path/to/autotest',
                            })
            }) +  #
            api.properties.environ(
                PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                        SWARMING_TASK_ID='dummy-task-id',
                                        SKYLAB_DUT_ID='dummy-dut-id')))

  yield api.test(
      'basic',
      _misc_properties(),
  )
