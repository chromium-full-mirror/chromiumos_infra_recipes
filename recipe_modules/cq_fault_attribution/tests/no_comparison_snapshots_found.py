# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStatus
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFaultAttributionApiProperties
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cq_fault_attribution',
    'looks_for_green',
    'skylab_results',
]


LFG_COMMIT_SHA = 'lfgcommitsha'
ORCH_SNAPSHOT_COMMIT_SHA = 'orchsnapshotcommitsha'

pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
passing_test_cases = [
    ExecuteResponse.TaskResult.TestCaseResult(name='test1',
                                              verdict=TaskState.VERDICT_PASSED),
]
child_results = [
    ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                               test_cases=passing_test_cases),
]


def RunSteps(api):
  hw_tests = [
      SkylabResult(
          task=api.skylab_results.test_api.skylab_task(suite='suite1'),
          status=common_pb2.FAILURE, child_results=child_results),
  ]
  orch_snapshot = \
    GitilesCommit(
        host='chrome-internal.googlesource.com',
        project='chromeos/manifest-internal',
        id=ORCH_SNAPSHOT_COMMIT_SHA,
        ref='refs/heads/snapshot')

  # Testing the case of when no comparison snapshots are found with using the
  # orchestrator commit sha.
  cq_test_failure_attributes = \
    api.cq_fault_attribution.set_cq_fault_attribute_properties(
      MetaTestTuple(skylab=hw_tests, autotest_vm=[], tast_vm=[], tast_gce=[]),
      orch_snapshot)
  api.assertions.assertEqual(
      len(cq_test_failure_attributes.test_failure_attributions), 0)

  # Testing the case of when no comparison snapshots are found with using the
  # commit sha selected by LFG.
  api.looks_for_green.stats.status = LooksForGreenStatus.STATUS_RAN_OLDER
  cq_test_failure_attributes = \
    api.cq_fault_attribution.set_cq_fault_attribute_properties(
      MetaTestTuple(skylab=hw_tests, autotest_vm=[], tast_vm=[], tast_gce=[]),
      orch_snapshot)
  api.assertions.assertEqual(
      len(cq_test_failure_attributes.test_failure_attributions), 0)


def GenTests(api):
  yield api.test(
      'no-comparison-snapshots',
      api.properties(
          **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }))
