# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import copy

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_engine.result import RawResult
from PB.recipe_modules.chromeos.snapshot_orch_menu.examples.full import FullProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
    'checkpoint',
    'cros_source',
    'cros_tags',
    'cros_test_plan',
    'gerrit',
    'git_footers',
    'snapshot_orch_menu',
    'skylab',
]

PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.checkpoint.register()

  build = api.buildbucket.build
  build.input.experiments.extend(properties.experiments)
  with api.snapshot_orch_menu.setup_orchestrator() as config:
    api.assertions.assertEqual(config, api.snapshot_orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return None
    api.assertions.assertIsNotNone(config)

    api.assertions.assertEqual(api.snapshot_orch_menu.skip_paygen,
                               properties.skip_paygen)

    is_postsubmit_orch = build.builder.builder == 'postsubmit-orchestrator'
    api.assertions.assertEqual(
        api.snapshot_orch_menu.is_postsubmit_orchestrator, is_postsubmit_orch)

    # It's hard to set buildbucket properties for these tests so we
    # get coverage by creating a dict that returns multiple items with the
    # same key, knowing that the impl of this module calls dict.items().
    class FakeDict():

      def __init__(self):
        pass

      def items(self):
        return [('foo', 'bar'), ('foo', lambda: 'baz')]

    f = FakeDict()

    if properties.use_extra_props:
      builds_status = api.snapshot_orch_menu.plan_and_run_children(
          extra_child_props=f)
    else:
      builds_status = api.snapshot_orch_menu.plan_and_run_children()

    if not builds_status.fatal_failures:
      builds_status = api.snapshot_orch_menu.plan_and_run_tests()

    if properties.process_child:
      api.snapshot_orch_menu.schedule_wait_build(
          properties.process_child, await_completion=True, check_failures=True,
          step_name='run %s' % properties.process_child)

    if properties.expected_completed_builds:
      for actual, expected in zip(
          api.snapshot_orch_menu.builds_status.completed_builds,
          properties.expected_completed_builds):
        api.assertions.assertEqual(actual, expected)

    expected = properties.expected_recipe_result
    if not expected.status:
      expected = RawResult(status=common_pb2.SUCCESS)
    actual = api.snapshot_orch_menu.create_recipe_result()
    api.assertions.assertEqual(expected.status, actual.status)
    return actual


def GenTests(api):
  data = api.snapshot_orch_menu.standard_test_data()

  def snapshot_orch_menu_properties(**kwargs):
    return {'$chromeos/snapshot_orch_menu': kwargs}

  yield api.snapshot_orch_menu.test(
      'basic', data.ctp_normal,
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/test.git push'),
      api.step_data('update manifest ref refs/heads/test.git push', retcode=1),
      api.step_data('update manifest ref refs/heads/test.git push (2)',
                    retcode=1),
      api.step_data('update manifest ref refs/heads/test.git push (3)',
                    retcode=1), input_properties=snapshot_orch_menu_properties(
                        update_manifest_refs={'test': 'refs/heads/test'}),
      builder='postsubmit-orchestrator', with_manifest_refs=True,
      collect_builds=data.builds, with_history=True)

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'orchestrator'
  original_build.output.properties[
      'buildspec_gs_uri'] = 'gs://chromeos-manifest-versions/foo/1.xml'
  original_build.output.properties['child_builds'] = [
      '8922054662172514002', '8922054662172514003'
  ]

  # TODO(b/245326818): Add useful assertions
  yield api.snapshot_orch_menu.test(
      'factory-orchestrator',
      input_properties=snapshot_orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main'),
      builder='factory-corsola-15197.B-orchestrator',
      with_history=True,
      bot_size='medium',
  )

  collect, _ = api.snapshot_orch_menu.orch_child_builds(
      'postsubmit-orchestrator', '-postsubmit')
  yield api.snapshot_orch_menu.test(
      'branch', data.ctp_normal, api.cros_source.snapshot_xml_exists(False),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/test.git push'),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.read git footers'),
      collect_builds=collect, input_properties=snapshot_orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'}),
      with_manifest_refs=True, with_history=True,
      sheriff_rotations=['chromeos'])

  summary = ('3 out of 3 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:'
             '\n\n- htarget.hw.some-other-suite:')
  yield api.snapshot_orch_menu.test(
      'test-failure',
      data.ctp_failure,
      api.properties(
          FullProperties(
              use_extra_props=True,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/test.git push'),
      input_properties=snapshot_orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'}),
      collect_builds=collect,
      with_manifest_refs=True,
      with_history=True,
      status='FAILURE',
  )

  yield api.snapshot_orch_menu.test(
      'bad-ref',
      api.properties(FullProperties(expect_missing_config=True)),
      input_properties=snapshot_orch_menu_properties(
          update_manifest_refs={'start': 'missing-ref-heads'}),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.snapshot_orch_menu.test(
      'bad-failure-ratio',
      api.properties(FullProperties(expect_missing_config=True)),
      input_properties=snapshot_orch_menu_properties(
          update_manifest_refs={'max_build_failure_ratio': 1.1}),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.snapshot_orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config', with_manifest_refs=True)

  yield api.snapshot_orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False),
      cq=True,
      with_history=True,
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  one_non_crit_fail_summary = ('1 non-critical build failed')
  # Collect times out
  yield api.snapshot_orch_menu.test(
      'collect-children-timeout', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary))),
      api.step_data('run builds.collect.wait', retcode=1),
      collect_builds=data.builds, history_builds=data.history_builds,
      collect_timeout=True, with_manifest_refs=True, with_history=True)

  yield api.snapshot_orch_menu.test(
      'quota-scheduler-override', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary))),
      collect_builds=data.builds, history_builds=data.history_builds, cq=True,
      with_history=True, git_footers=[],
      tags=api.cros_tags.tags(cq_cl_tag='pupr:chromeos-base/lacros-ash-atomic'))

  # Process-child
  yield api.snapshot_orch_menu.test(
      'with-process-child', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + [data.process_child],
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary),
              process_child=data.process_child.builder.builder,
          )), collect_builds=data.builds, history_builds=data.history_builds,
      process_child=data.process_child, bucket='toolchain',
      builder='artifact-generate-orchestrator')

  # Process-child times out.
  yield api.snapshot_orch_menu.test(
      'with-process-child-timeout', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=data.builds + [data.process_child],
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary),
              process_child=data.process_child.builder.builder,
          )), collect_builds=data.builds, history_builds=data.history_builds,
      process_child=data.process_child, process_child_timeout=True,
      bucket='toolchain', builder='artifact-generate-orchestrator')

  yield api.snapshot_orch_menu.test(
      'chromium-src-ref-cq-cl-tag', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary))),
      api.buildbucket.ci_build(
          project='chromeos', bucket='postsubmit',
          builder='postsubmit-orchestrator',
          tags=api.cros_tags.tags(cq_cl_tag='chromium_src_ref:foo1234ref')),
      collect_builds=data.builds)

  input_props = snapshot_orch_menu_properties(
      update_manifest_refs={'test': 'refs/heads/test'})
  input_props.update({
      '$chromeos/cros_test_plan_v2': {
          'migration_configs': [{
              'host': 'chromium.googlesource.com',
              'project': 'chromiumos/platform',
              'file_allowlist_regexps': ['a/b/.*'],
              'branch_allowlist_regexps': ['.*'],
          },]
      }
  })

  gerrit_changes = [
      GerritChange(
          host='chromium.googlesource.com',
          project='chromiumos/platform',
          change=1234,
          patchset=5,
      ),
  ]

  input_props_with_generate_ctpv1_format = copy.deepcopy(input_props)
  input_props_with_generate_ctpv1_format['$chromeos/cros_test_plan_v2'][
      'generate_ctpv1_format'] = True
  yield api.snapshot_orch_menu.test(
      'ctp2-enabled-generate-ctpv1-format',
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled',
          gerrit_changes,
          {
              1234: {
                  'patch_set': 5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch': 'main',
              },
          },
      ),
      data.ctp_normal,
      collect_builds=api.snapshot_orch_menu.orch_child_builds(
          'postsubmit-orchestrator', '-postsubmit')[0],
      input_properties=input_props_with_generate_ctpv1_format,
      builder='postsubmit-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      extra_changes=gerrit_changes,
  )

  summary = ('3 out of 3 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:'
             '\n\n- htarget.hw.some-other-suite:')
  yield api.snapshot_orch_menu.test(
      'ctp2-enabled-generate-ctpv1-format-test-failure',
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled',
          gerrit_changes,
          {
              1234: {
                  'patch_set': 5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch': 'main',
              },
          },
      ),
      data.ctp_failure,
      input_properties=input_props_with_generate_ctpv1_format,
      builder='postsubmit-orchestrator',
      collect_builds=data.builds,
      with_manifest_refs=True,
      with_history=True,
      extra_changes=gerrit_changes,
      status='FAILURE',
  )

  annealing_build_with_found_changes = build_pb2.Build()
  annealing_build_with_found_changes.output.properties[
      'found_gerrit_changes'] = [
          json_format.MessageToJson(gc) for gc in [
              GerritChange(
                  host='chromium.googlesource.com',
                  project='chromiumos/platform',
                  change=1234,
                  patchset=5,
              ),
              GerritChange(
                  host='chromium.googlesource.com',
                  project='chromiumos/platform',
                  change=5678,
                  patchset=2,
              ),
          ]
      ]

  yield api.snapshot_orch_menu.test(
      'snapshot-orch-v2-test-planning',
      api.properties(
          FullProperties(experiments=[
              'chromeos.snapshot_orch_menu.plan_tests_using_snapshot'
          ])),
      api.buildbucket.simulated_search_results(
          [annealing_build_with_found_changes],
          'find changes in snapshot.buildbucket.search'),
      api.post_process(
          post_process.StepCommandContains,
          'find changes in snapshot.buildbucket.search', [
              '-predicate',
              '{\"builder\": {\"project\": \"chromeos\"}, \"tags\": [{\"key\": \"published_snapshot_id\", \"value\": \"snapshot-HEAD-SHA\"}]}'
          ]),
      api.post_process(post_process.StepTextEquals, 'find changes in snapshot',
                       'found 2 changes from snapshot snapshot-HEAD-SHA'),
      api.post_process(post_process.StepTextEquals,
                       'check test planning v2 enabled',
                       'enabling test planning v2'),
      api.post_process(post_process.DropExpectation),
      builder='snapshot-orchestrator',
      input_properties={
          '$chromeos/cros_test_plan_v2': {
              'generate_ctpv1_format':
                  True,
              'migration_configs': [{
                  'host': 'chromium.googlesource.com',
                  'project': 'chromiumos/platform',
                  'file_allowlist_regexps': ['.*'],
                  'branch_allowlist_regexps': ['.*'],
              },]
          }
      },
  )

  yield api.snapshot_orch_menu.test(
      'snapshot-orch-v2-test-planning-annealing-not-found',
      api.properties(
          FullProperties(experiments=[
              'chromeos.snapshot_orch_menu.plan_tests_using_snapshot'
          ])),
      api.expect_exception('RuntimeError'),
      api.post_process(
          post_process.ResultReasonRE,
          'no annealing build found for snapshot_id snapshot-HEAD-SHA'),
      api.post_process(post_process.DropExpectation),
      builder='snapshot-orchestrator',
  )
