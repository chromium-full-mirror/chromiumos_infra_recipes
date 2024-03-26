# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFaultAttributionApiProperties
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStatus
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from recipe_engine import post_process

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
fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
passing_test_cases = [
    ExecuteResponse.TaskResult.TestCaseResult(name='test1',
                                              verdict=TaskState.VERDICT_PASSED),
]
failing_test_cases = [
    ExecuteResponse.TaskResult.TestCaseResult(
        name='test2', verdict=TaskState.VERDICT_FAILED,
        human_readable_summary='missing SoftwareDeps: android_vm'),
    ExecuteResponse.TaskResult.TestCaseResult(
        name='test3', verdict=TaskState.VERDICT_FAILED,
        human_readable_summary='missing SoftwareDeps: android_vm'),
    ExecuteResponse.TaskResult.TestCaseResult(
        name='tast.test4', verdict=TaskState.VERDICT_FAILED,
        human_readable_summary='missing SoftwareDeps: android_vm'),
    ExecuteResponse.TaskResult.TestCaseResult(
        name='tast', verdict=TaskState.VERDICT_FAILED,
        human_readable_summary='3 failures: test2, test3, tast.test4'),
]
unspecified_verdict_test_case = [
    ExecuteResponse.TaskResult.TestCaseResult(name='test5')
]
child_results = [
    ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                               test_cases=passing_test_cases),
    ExecuteResponse.TaskResult(
        name='suite2', state=fail_state,
        test_cases=(passing_test_cases + failing_test_cases)),
    ExecuteResponse.TaskResult(name='suite3', state=pass_state,
                               test_cases=passing_test_cases),
]
# Mock Orchestrator snapshot
output = build_pb2.Build.Output()
orch_snapshot_build = \
  build_pb2.Build(id=123, output=output, input=build_pb2.Build.Input())

# Mock Orchestrator postsubmit
orch_postsubmit_build = \
  build_pb2.Build(id=456, output=output, input=build_pb2.Build.Input())


def RunSteps(api):
  hw_test_failures = [
      SkylabResult(
          task=api.skylab_results.test_api.skylab_task(suite='suite1'),
          status=common_pb2.FAILURE, child_results=child_results),
      SkylabResult(task=api.skylab_results.test_api.skylab_task(),
                   status=common_pb2.SUCCESS, child_results=child_results[:1]),
  ]

  orch_snapshot = \
    GitilesCommit(
        host='chrome-internal.googlesource.com',
        project='chromeos/manifest-internal',
        id=ORCH_SNAPSHOT_COMMIT_SHA,
        ref='refs/heads/snapshot')
  api.looks_for_green.stats.suggested.snap_commit_sha = LFG_COMMIT_SHA

  if api.properties['should_use_lfg']:
    api.looks_for_green.stats.status = LooksForGreenStatus.STATUS_RAN_OLDER

  api.cq_fault_attribution.set_cq_fault_attribute_properties(
      MetaTestTuple(skylab=hw_test_failures, autotest_vm=[], tast_vm=[],
                    tast_gce=[]), orch_snapshot)


def GenTests(api):
  yield api.test(
      'orch-snapshot-commit-sha',
      api.properties(
          should_use_lfg=False, **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }),
      api.buildbucket.simulated_search_results(
          builds=[orch_postsubmit_build],
          step_name='set fault attributes.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[orch_snapshot_build],
          step_name='set fault attributes.buildbucket.search (2)'),
      api.post_process(
          post_process.StepCommandContains,
          'set fault attributes.buildbucket.search',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "postsubmit-orchestrator", "project": "chromeos"}}'
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'set fault attributes.buildbucket.search (2)',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "snapshot-orchestrator", "project": "chromeos"}, "tags": [{"key": "buildset", "value": "commit/gitiles/chrome-internal.googlesource.com/chromeos/manifest-internal/+/orchsnapshotcommitsha"}]}'
          ],
      ))

  yield api.test(
      'lfg-snapshot-commit-sha',
      api.properties(
          should_use_lfg=True, **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }),
      api.buildbucket.simulated_search_results(
          builds=[orch_postsubmit_build],
          step_name='set fault attributes.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[orch_snapshot_build],
          step_name='set fault attributes.buildbucket.search'),
      api.post_process(
          post_process.StepCommandContains,
          'set fault attributes.buildbucket.search',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "postsubmit-orchestrator", "project": "chromeos"}}'
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'set fault attributes.buildbucket.search (2)',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "snapshot-orchestrator", "project": "chromeos"}, "tags": [{"key": "buildset", "value": "commit/gitiles/chrome-internal.googlesource.com/chromeos/manifest-internal/+/lfgcommitsha"}]}'
          ],
      ))
