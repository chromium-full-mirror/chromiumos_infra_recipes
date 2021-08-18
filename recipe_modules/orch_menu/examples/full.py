# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_source',
    'cros_tags',
    'gerrit',
    'git_footers',
    'orch_menu',
    'skylab',
    'test_util',
]

from google.protobuf import json_format
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

    api.assertions.assertEqual(api.orch_menu.is_release_orchestrator,
                               properties.is_release_orchestrator)
    is_postsubmit_orch = build.builder.builder == 'postsubmit-orchestrator'
    api.assertions.assertEqual(api.orch_menu.is_postsubmit_orchestrator,
                               is_postsubmit_orch)

    expected_changes = build.input.gerrit_changes
    # Add any changes from the config.
    expected_changes.extend([
        json_format.Parse(json_format.MessageToJson(x), GerritChange())
        for x in config.orchestrator.gerrit_changes
    ])
    api.assertions.assertEqual(
        str(expected_changes), str(api.orch_menu.gerrit_changes))

    api.assertions.assertEqual(
        api.orch_menu.is_dry_run,
        api.cq.active and api.cq.run_mode == api.cq.DRY_RUN,
    )

    # It's hard to set buildbucket properties for these tests so we
    # get coverage by creating a dict that returns multiple items with the
    # same key, knowing that the impl of this module calls dict.items().
    class FakeDict(object):

      def __init__(self):
        pass

      def items(self):
        return [('foo', 'bar'), ('foo', 'baz')]

    f = FakeDict()

    if properties.use_extra_props:
      builds_status = api.orch_menu.plan_and_run_children(extra_child_props=f)
    else:
      builds_status = api.orch_menu.plan_and_run_children()

    if not builds_status.fatal_failures:
      builds_status = api.orch_menu.plan_and_run_tests()

    if properties.process_child:
      api.orch_menu.schedule_wait_build(
          properties.process_child, await_completion=True, check_failures=True,
          step_name='run %s' % properties.process_child)

    api.orch_menu.run_follow_on_orchestrator()

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

  yield api.orch_menu.test(
      'basic', data.ctp_normal, api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/test.git push'),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(test='refs/heads/test')),
      builder='postsubmit-orchestrator', with_manifest_refs=True,
      with_history=True)

  yield api.orch_menu.test(
      'release-orchestrator', data.ctp_normal,
      api.properties(
          FullProperties(is_release_orchestrator=True, use_extra_props=True)),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/test.git push'),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(test='refs/heads/test')),
      builder='main-release-orchestrator', with_manifest_refs=True,
      with_history=True, bot_size='medium')

  yield api.orch_menu.test(
      'branch', data.ctp_normal, api.post_check(post_process.StatusSuccess),
      api.cros_source.snapshot_xml_exists(False),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/test.git push'),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.read git footers'),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(test='refs/heads/test')),
      with_manifest_refs=True, with_history=True)

  summary = ('2 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:')
  yield api.orch_menu.test(
      'test-failure', data.ctp_failure,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/test.git push'),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(test='refs/heads/test')),
      with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
      'bad-ref',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(start='missing-ref-heads')))

  yield api.orch_menu.test(
      'bad-failure-ratio',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=orch_menu_properties(
          update_manifest_refs=dict(max_build_failure_ratio=1.1)))

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
      history_builds=data.history_builds, with_history=True,
      with_manifest_refs=True)

  # Joins an inflight orchestrator run.
  yield api.orch_menu.test(
      'inflight-orchestrator', data.ctp_normal,
      api.post_check(post_process.MustRun, 'find inflight orchestrator'),
      api.post_check(
          post_process.MustRun,
          'find inflight orchestrator.waiting for existing runs.wait'),
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + data.after_builds,
              expected_enable_history=True)), cq=True,
      collect_builds=data.builds, history_builds=data.history_builds,
      collect_after_builds=data.after_builds, with_history=True, git_footers=[],
      inflight_orch=[data.inflight_orchestrator])

  # Runs when there is no inflight orchestrator.
  yield api.orch_menu.test(
      'no-inflight-orchestrator', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + data.after_builds,
              expected_enable_history=True)), cq=True,
      collect_builds=data.builds, history_builds=data.history_builds,
      collect_after_builds=data.after_builds, with_history=True, git_footers=[],
      inflight_orch=[])

  # Collect times out
  yield api.orch_menu.test('collect-children-timeout', data.ctp_normal,
                           api.step_data('run builds.collect.wait',
                                         retcode=1), collect_builds=data.builds,
                           history_builds=data.history_builds,
                           collect_timeout=True, with_manifest_refs=True,
                           with_history=True)

  yield api.orch_menu.test(
      'quota-scheduler-override', data.ctp_normal, collect_builds=data.builds,
      history_builds=data.history_builds, cq=True, with_history=True,
      git_footers=[],
      tags=api.cros_tags.tags(cq_cl_tag='pupr:chromeos-base/chromeos-chrome'))

  yield api.orch_menu.test(
      'lts-pupr-noop', data.ctp_normal,
      api.post_check(post_process.DoesNotRun, 'run builds|schedule new builds'),
      builder='lts-cq-release-R90-13816.B-orchestrator', cq=True,
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
          )), collect_builds=data.builds, history_builds=data.history_builds,
      process_child=data.process_child,
      follow_on_orch=data.follow_on_orchestrator, bucket='toolchain',
      builder='orderfile-generate-orchestrator')

  # Process-child times out.
  yield api.orch_menu.test(
      'with-process-child-timeout', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + [data.process_child],
              process_child=data.process_child.builder.builder,
          )), collect_builds=data.builds, history_builds=data.history_builds,
      process_child=data.process_child, process_child_timeout=True,
      follow_on_orch=data.follow_on_orchestrator, bucket='toolchain',
      builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator.
  yield api.orch_menu.test(
      'with-follow-on', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds +
                         [data.follow_on_orchestrator])),
      collect_builds=data.builds, history_builds=data.history_builds,
      follow_on_orch=data.follow_on_orchestrator, bucket='toolchain',
      builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator times out.
  yield api.orch_menu.test(
      'with-follow-on-timeout', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.builds +
                         [data.follow_on_orchestrator])),
      collect_builds=data.builds, history_builds=data.history_builds,
      follow_on_orch=data.follow_on_orchestrator, follow_on_timeout=True,
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  summary = (
      '1 build failed\n\n- amd64-generic-postsubmit: [build page](https://'
      'cr-buildbucket.appspot.com/build/8922054662172514000)')
  yield api.orch_menu.test(
      'critical_child_builder_fails',
      api.post_check(post_process.StatusAnyFailure),
      api.properties(
          FullProperties(
              expected_completed_builds=data.crit_fail,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      collect_builds=data.crit_fail, history_builds=data.history_builds,
      with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
      'non-critical_child_builder_fails', data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=data.non_crit_fail)),
      collect_builds=data.non_crit_fail, history_builds=data.history_builds,
      with_manifest_refs=True, with_history=True)
