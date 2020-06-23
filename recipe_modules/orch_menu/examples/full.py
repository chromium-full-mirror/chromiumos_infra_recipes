# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_bisect',
    'gerrit',
    'orch_menu',
    'test_util',
]

from google.protobuf import json_format

from PB.recipe_modules.chromeos.orch_menu.examples.full import FullProperties
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipe_modules.chromeos.cros_bisect import cros_bisect
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.rpc import BatchResponse
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

PROPERTIES = FullProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(
      missing_ok=properties.missing_ok,
      test_footers=properties.test_footers) as config:
    api.assertions.assertEqual(config, api.orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return
    api.assertions.assertIsNotNone(config)
    api.orch_menu.assert_changes_submittable()

    expected_changes = api.buildbucket.build.input.gerrit_changes
    expected_changes.extend([
        json_format.Parse(json_format.MessageToJson(x), GerritChange())
        for x in config.orchestrator.gerrit_changes
    ])
    api.assertions.assertEqual(
        str(expected_changes), str(api.orch_menu.gerrit_changes))

    api.orch_menu.push_manifest_refs('refs/heads/postsubmit')

    api.orch_menu.wait_for_inflight_orchestrator()
    completed = api.orch_menu.plan_and_run_children()
    follow_on = config.orchestrator.follow_on_orchestrator
    if follow_on.name:
      completed.append(
          api.orch_menu.schedule_wait_build(follow_on.name,
                                            follow_on.await_completion))
    if properties.expected_completed_builds:
      for actual, expected in zip(completed,
                                  properties.expected_completed_builds):
        expected = json_format.Parse(expected, Build())
        api.assertions.assertEqual(actual, expected)


def GenTests(api):

  running_orch = [
      api.test_util.test_orchestrator(cq=True, build_id=8922054662172514000,
                                      status='STARTED').message
  ]
  successful_orch = [
      api.test_util.test_orchestrator(cq=True, build_id=8922054662172514000,
                                      status='SUCCESS').message
  ]
  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  builds = [
      api.test_util.test_child_build(
          'amd64-generic', cq=True, build_id=8922054662172514000,
          status='SUCCESS', output_properties=dict(build_cost=10.0)).message,
      api.test_util.test_child_build('arm-generic', cq=True,
                                     build_id=8922054662172514001,
                                     status='STARTED').message,
      api.test_util.test_child_build('atlas', cq=True,
                                     build_id=8922054662172514002,
                                     start_time=1562475245, status='SUCCESS',
                                     revision=None).message,
  ]

  def list_to_json(items):
    return [json_format.MessageToJson(x) for x in items]

  yield api.orch_menu.test('basic')

  yield api.orch_menu.test(
      'two-footers',
      api.properties(
          FullProperties(expect_missing_config=True,
                         test_footers='foot1\nfoot2')))

  yield api.orch_menu.test(
      'bad-ref',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=OrchestratorProperties(
          update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
              start='missing-ref-heads')))

  yield api.orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config')

  yield api.orch_menu.test(
      'forgiven-missing-config',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      builder='no-config')

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False), cq=True)

  # Joins an inflight orchestrator run.
  yield api.orch_menu.test(
      'inflight-orchestrator',
      api.buildbucket.simulated_search_results(
          running_orch, step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          successful_orch,
          'find inflight orchestrator.waiting for existing runs'),
      api.properties(expected_completed_builds=list_to_json(builds)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
  )

  # Collect times out
  yield api.orch_menu.test(
      'collect-children-timeout',
      api.step_data('run builds.collect.wait', retcode=1),
      api.buildbucket.simulated_get_multi(builds, 'run builds.get'),
  )

  # Bisection
  yield api.orch_menu.test(
      'with-test-bisection',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  cros_bisect.CrosBisectProperties(
                      test=dict(hw_test_failures=[
                          dict(
                              test_spec=json_format.MessageToJson(hw_test_unit))
                      ]))
          }),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      api.properties(expected_completed_builds=list_to_json(builds)),
      bucket='bisect', builder='bisecting-orchestrator')

  # Follow-on orchestrator.
  yield api.orch_menu.test(
      'with-follow-on',
      api.properties(
          expected_completed_builds=list_to_json(builds + successful_orch)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          BatchResponse(responses=[dict(schedule_build=running_orch[0])]),
          'run follow on orchestrator.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          successful_orch, 'run follow on orchestrator.collect'),
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator times out.
  yield api.orch_menu.test(
      'with-follow-on-timeout',
      api.properties(
          expected_completed_builds=list_to_json(builds + successful_orch)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          BatchResponse(responses=[dict(schedule_build=running_orch[0])]),
          'run follow on orchestrator.buildbucket.schedule'),
      api.step_data('run follow on orchestrator.collect.wait', retcode=1),
      api.buildbucket.simulated_get_multi(successful_orch,
                                          'run follow on orchestrator.get'),
      bucket='toolchain', builder='orderfile-generate-orchestrator')
