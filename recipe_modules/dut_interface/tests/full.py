# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.phosphorus.phosphorus import PhosphorusEnvProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import PhosphorusProperties
from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import CrosToolRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import CrosToolRunnerEnvProperties

DEPS = [
    'recipe_engine/buildbucket', 'recipe_engine/context',
    'recipe_engine/properties', 'recipe_engine/raw_io', 'recipe_engine/step',
    'recipe_engine/time', 'recipe_engine/uuid', 'dut_interface', 'phosphorus'
]


PROPERTIES = TestRunnerProperties


def RunSteps(api, properties):
  api.dut_interface.create(api, properties)

def GenTests(api):

  def _get_test_runner_properties(cft_is_enabled=False):
    return TestRunnerProperties(
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
        }, cft_is_enabled=cft_is_enabled)

  def _misc_properties_for_ctr():
    return (api.properties(
        _get_test_runner_properties(cft_is_enabled=True), **{
            '$chromeos/phosphorus':
                PhosphorusProperties(
                    version=PhosphorusProperties.Version(
                        cipd_label='phosphorus_prod'), config={
                            'admin_service': 'foo-service',
                            'cros_inventory_service': 'inv-service',
                            'cros_ufs_service': 'ufs-service',
                            'autotest_dir': '/path/to/autotest',
                        }),
            '$chromeos/cros_tool_runner':
                CrosToolRunnerProperties(
                    version=CrosToolRunnerProperties.Version(
                        cipd_label='cros_tool_runner_prod'))
        }) + api.properties.environ(
            PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                    SWARMING_TASK_ID='dummy-task-id',
                                    SKYLAB_DUT_ID='dummy-dut-id')) +
            api.properties.environ(
                CrosToolRunnerEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                            SWARMING_TASK_ID='dummy-task-id',
                                            SKYLAB_DUT_ID='dummy-dut-id')))

  def _misc_properties_for_phosphorus():
    return (api.properties(
        _get_test_runner_properties(), **{
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
      'basic-phosphorus',
      _misc_properties_for_phosphorus(),
  )

  yield api.test(
      'basic-ctr',
      _misc_properties_for_ctr(),
  )
