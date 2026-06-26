# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring

"""Tests for skylab.batch_requests."""

from google.protobuf import duration_pb2
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
    'metadata',
    'skylab',
]


def RunSteps(api):

  def _create_unit_hw_test(build_target, suite):
    hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
    hw_test_unit.common.build_target.name = build_target
    hw_test_unit.common.builder_name = build_target
    hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
    hw_test.skylab_board = build_target
    hw_test.common.display_name = f'{build_target}.hw.{suite}'
    unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)
    return unit_hw_test


  requests_dict = {}
  requests_dict["dedede-drallion--R132"] = {"test plan 1"}
  batch_size = 3
  batched_requests = api.skylab.batch_requests(requests_dict, batch_size)
  api.assertions.assertEqual(len(batched_requests), 1)

  requests_dict["dedede-drallion360--R132"] = {"test plan 2"}
  requests_dict["dedede-gothrax--R133"] = {"test plan 3"}
  requests_dict["dedede-drallion36--R132"] = {"test plan 4"}
  batched_requests = api.skylab.batch_requests(requests_dict, batch_size)
  total_reqs = 0
  for batch_req in batched_requests:
    total_reqs += len(batch_req)
  api.assertions.assertEqual(len(batched_requests), 2)
  api.assertions.assertEqual(total_reqs, 4)


  # Test that we return the correct amount of skylab tasks and that the batching
  # resulted in the correct number of cros_test_platform builds.
  unit_hw_tests = [_create_unit_hw_test('target', i) for i in range(101)]
  skylab_tasks = api.skylab.schedule_suites(
      unit_hw_tests, timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(target='target'),
      async_suite_run=True)
  api.assertions.assertEqual(len(skylab_tasks), len(unit_hw_tests))
  ctp_build_count = {x.id for x in skylab_tasks}
  api.assertions.assertEqual(len(ctp_build_count), 2)

def GenTests(api):

  yield api.test(
      'batch_request',
      api.post_process(post_process.DropExpectation),
  )
