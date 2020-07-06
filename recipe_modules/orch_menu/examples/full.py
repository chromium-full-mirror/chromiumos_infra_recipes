# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_tags',
    'gerrit',
    'git_footers',
    'orch_menu',
    'skylab',
    'test_util',
]

from google.protobuf import json_format
from recipe_engine import recipe_test_api
from recipe_engine import post_process

from PB.recipe_modules.chromeos.orch_menu.examples.full import FullProperties
from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

PROPERTIES = FullProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  with api.orch_menu.setup_orchestrator(
      missing_ok=properties.missing_ok,
      test_footers=properties.test_footers) as config:
    api.assertions.assertEqual(config, api.orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return
    api.assertions.assertIsNotNone(config)

    expected_changes = build.input.gerrit_changes
    # Add any changes from the config.
    expected_changes.extend([
        json_format.Parse(json_format.MessageToJson(x), GerritChange())
        for x in config.orchestrator.gerrit_changes
    ])
    api.assertions.assertEqual(
        str(expected_changes), str(api.orch_menu.gerrit_changes))

    builds_status = api.orch_menu.plan_and_run_children()

    if not builds_status.fatal_failures:
      builds_status = api.orch_menu.plan_and_run_tests()

    if properties.process_child:
      api.orch_menu.schedule_wait_build(
          properties.process_child, await_completion=True, check_failures=True,
          step_name='run %s' % properties.process_child)

    follower = config.orchestrator.follow_on_orchestrator
    if follower.name:
      api.orch_menu.schedule_wait_build(follower.name,
                                        follower.await_completion)

    if properties.expected_completed_builds:
      for actual, expected in zip(api.orch_menu.builds_status.completed_builds,
                                  properties.expected_completed_builds):
        api.assertions.assertEqual(actual, expected)

    expected = properties.expected_recipe_result
    if not expected.status:
      expected = RawResult(status=common_pb2.SUCCESS)
    actual = api.orch_menu.create_recipe_result()
    api.assertions.assertEqual(expected, actual)
    return actual


def GenTests(api):
  data = api.orch_menu.standard_test_data()

  def orch_menu_properties(**kwargs):
    return {'$chromeos/orch_menu': kwargs}

  yield api.orch_menu.test('basic', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
      'two-footers',
      api.properties(
          FullProperties(expect_missing_config=True,
                         test_footers='foot1\nfoot2')), with_manifest_refs=True,
      with_history=True)

  yield api.orch_menu.test(
      'bad-ref',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(start='missing-ref-heads')))

  yield api.orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config', with_manifest_refs=True)

  yield api.orch_menu.test(
      'forgiven-missing-config',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      builder='no-config', with_manifest_refs=True)

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False), cq=True,
      with_history=True)

  # Annealing builds.
  yield api.orch_menu.test(
      'existing-annealing-builds', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds,
                         expected_enable_history=True)),
      annealing_builds=data.annealing_builds, collect_builds=data.builds,
      with_history=True, with_manifest_refs=True)

  # Joins an inflight orchestrator run.
  yield api.orch_menu.test(
      'inflight-orchestrator', data.ctp_normal,
      api.post_check(post_process.MustRun, 'find inflight orchestrator'),
      api.post_check(
          post_process.MustRun,
          'find inflight orchestrator.waiting for existing runs.wait'),
      api.properties(
          FullProperties(expected_completed_builds=data.builds,
                         expected_enable_history=True)), cq=True,
      collect_builds=data.builds, with_history=True, git_footers=[],
      inflight_orch=[data.inflight_orchestrator])

  # Runs when there is no inflight orchestrator.
  yield api.orch_menu.test(
      'no-inflight-orchestrator', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds,
                         expected_enable_history=True)), cq=True,
      collect_builds=data.builds, with_history=True, git_footers=[],
      inflight_orch=[])

  # Collect times out
  yield api.orch_menu.test('collect-children-timeout', data.ctp_normal,
                           api.step_data('run builds.collect.wait', retcode=1),
                           collect_builds=data.builds, collect_timeout=True,
                           with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
      'quota-scheduler-override', data.ctp_normal, collect_builds=data.builds,
      cq=True, with_history=True, git_footers=[],
      tags=api.cros_tags.tags(cq_cl_tag='pupr:chromeos-base/chromeos-chrome'))

  # Bisection
  yield api.orch_menu.test(
      'with-test-bisection',
      api.properties(
          FullProperties(expected_completed_builds=data.bisect_builds)),
      data.bisect_properties, data.ctp_bisect,
      collect_builds=data.bisect_builds, with_history=True, bucket='bisect',
      builder='bisecting-orchestrator')

  # Process-child
  yield api.orch_menu.test(
      'with-process-child', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + [data.process_child],
              process_child=data.process_child.builder.builder,
          )), collect_builds=data.builds, process_child=data.process_child,
      follow_on_orch=data.follow_on_orchestrator, bucket='toolchain',
      builder='orderfile-generate-orchestrator')

  # Process-child times out.
  yield api.orch_menu.test(
      'with-process-child-timeout', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + [data.process_child],
              process_child=data.process_child.builder.builder,
          )), collect_builds=data.builds, process_child=data.process_child,
      process_child_timeout=True, follow_on_orch=data.follow_on_orchestrator,
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator.
  yield api.orch_menu.test(
      'with-follow-on', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds +
                         [data.follow_on_orchestrator])),
      collect_builds=data.builds, follow_on_orch=data.follow_on_orchestrator,
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator times out.
  yield api.orch_menu.test(
      'with-follow-on-timeout', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds +
                         [data.follow_on_orchestrator])),
      collect_builds=data.builds, follow_on_orch=data.follow_on_orchestrator,
      follow_on_timeout=True, bucket='toolchain',
      builder='orderfile-generate-orchestrator')

  summary = (
      '1 build failed\n\n- amd64-generic-postsubmit: [build page](https://'
      'beefy-dot-cr-buildbucket.appspot.com/build/8922054662172514000)')
  yield api.orch_menu.test(
      'critical_child_builder_fails',
      api.post_check(post_process.StatusAnyFailure),
      api.properties(
          FullProperties(
              expected_completed_builds=data.crit_fail,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      collect_builds=data.crit_fail, with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
      'non-critical_child_builder_fails', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.non_crit_fail)),
      collect_builds=data.non_crit_fail, with_manifest_refs=True,
      with_history=True)
