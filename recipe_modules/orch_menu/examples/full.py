# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import copy

from google.protobuf import json_format

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_engine.result import RawResult
from PB.recipe_modules.chromeos.orch_menu.examples.full import FullProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
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
    'orch_menu',
    'skylab',
]


PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.checkpoint.register()

  build = api.buildbucket.build
  with api.orch_menu.setup_orchestrator() as config:
    api.assertions.assertEqual(config, api.orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return None
    api.assertions.assertIsNotNone(config)

    api.assertions.assertEqual(api.orch_menu.skip_paygen,
                               properties.skip_paygen)

    api.assertions.assertEqual(api.orch_menu.is_release_orchestrator,
                               properties.is_release_orchestrator)
    if api.orch_menu.is_release_orchestrator:
      api.skylab.set_qs_account('release_high_prio')

    _ = api.orch_menu.is_public_orchestrator
    _ = api.orch_menu.is_factory_orchestrator
    is_cq_orch = build.builder.builder == 'cq-orchestrator'
    api.assertions.assertEqual(api.orch_menu.is_cq_orchestrator, is_cq_orch)

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
        api.cv.active and api.cv.run_mode == api.cv.DRY_RUN,
    )

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
      builds_status = api.orch_menu.plan_and_run_children(extra_child_props=f)
    else:
      builds_status = api.orch_menu.plan_and_run_children()

    if not builds_status.fatal_failures:
      builds_status = api.orch_menu.plan_and_run_tests()

    if properties.process_child:
      api.orch_menu.schedule_wait_build(
          properties.process_child, await_completion=True, check_failures=True,
          step_name='run %s' % properties.process_child)

    if properties.expected_completed_builds:
      for actual, expected in zip(api.orch_menu.builds_status.completed_builds,
                                  properties.expected_completed_builds):
        api.assertions.assertEqual(actual, expected)


    expected = properties.expected_recipe_result
    if not expected.status:
      expected = RawResult(status=common_pb2.SUCCESS)
    if api.orch_menu.is_cq_orchestrator:
      actual = api.orch_menu.create_cq_orch_recipe_result()
    else:
      actual = api.orch_menu.create_recipe_result(
          include_build_details=api.orch_menu.is_release_orchestrator)
    api.assertions.assertEqual(expected.status, actual.status)
    return actual


def GenTests(api):
  data = api.orch_menu.standard_test_data()

  def orch_menu_properties(**kwargs):
    return {'$chromeos/orch_menu': kwargs}

  yield api.orch_menu.test(
      'release-orchestrator',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0')),
      ),
      api.post_check(post_process.StepTextEquals,
                     'set up orchestrator.bump version', ''),
      # Uprev logic should not run on ToT.
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.uprev packages'),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.push uprevs'),
      api.post_check(
          post_process.MustRun,
          'set up orchestrator.create buildspec.upload buildspecs/99/1234.56.0.xml to gs://buildspecbucket/buildspecs/99/1234.56.0.xml'
      ),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.schedule public build'),
      api.post_check(
          post_process.StepCommandContains,
          'set up orchestrator.create buildspec.create external buildspec gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml',
          [
              'public-buildspec', '--paths', 'buildspecs/99/1234.56.0.xml',
              '--push'
          ]),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True,
          schedule_public_build=True,
          retry_allowlist_qs_account=['release_high_prio'],
          retry_allowlist_build_target=['atlas', 'zork']),
      builder='release-main-orchestrator',
      collect_builds=api.orch_menu.orch_child_builds(
          'release-main-orchestrator', '-release-main')[0],
      with_manifest_refs=True,
      with_history=True,
      sheriff_rotations=['chromeos'],
      bot_size='medium',
  )

  # Test custom build cadence feature.
  yield api.orch_menu.test(
      'release-orchestrator-custom-build-cadence',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0')),
      ),
      # Seed time to Tuesday, April 25, 2023 9:42:34 AM GMT-06:00.
      # So the weekday should be '2'.
      api.time.seed(1682437354),
      # In test_builder_configs.json, eve-release-main is configured to run
      # only on even days.
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.eve-release-main'),
      # In test_builder_configs.json, kukui-release-main is configured to run
      # only on odd days.
      api.post_check(
          post_process.StepTextContains,
          'run builds.schedule new builds.kukui-release-main',
          ['kukui-release-main configured to run on days 1,3,5, today is 2']),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True,
          retry_allowlist_qs_account=['release_high_prio'],
          retry_allowlist_build_target=['atlas',
                                        'zork'], custom_build_cadence=True),
      builder='release-main-orchestrator',
      collect_builds=[
          build for build in api.orch_menu.orch_child_builds(
              'release-main-orchestrator', '-release-main')[0]
          if build.builder.builder == 'eve-release-main'
      ],
      with_manifest_refs=True,
      with_history=True,
      sheriff_rotations=['chromeos'],
      bot_size='medium',
  )

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'orchestrator'
  original_build.output.properties[
      'buildspec_gs_uri'] = 'gs://chromeos-manifest-versions/foo/1.xml'
  original_build.output.properties['child_builds'] = ['8922054662172514002']

  child_build = build_pb2.Build(id=8922054662172514002, status='FAILURE')
  child_build.input.properties['recipe'] = 'build_release'

  yield api.orch_menu.test(
      'release-orchestrator-retry-run-children',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0'))),
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.RUN_CHILDREN]
                  },
              },
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(
          post_process.MustRun,
          'set up orchestrator.(RETRY-MODE) not retrying CREATE_BUILDSPEC'),
      api.post_check(
          post_process.DoesNotRun,
          'set up orchestrator.(RETRY-MODE) not retrying RUN_CHILDREN'),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True),
      builder='release-main-orchestrator',
      collect_builds=api.orch_menu.orch_child_builds(
          'release-main-orchestrator', '-release-main')[0],
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
  )

  child_build = build_pb2.Build(id=8922054662172514002, status='SUCCESS',
                                builder={'builder': 'eve-release-main'})
  child_build.input.properties['recipe'] = 'build_release'
  yield api.orch_menu.test(
      'release-orchestrator-retry-launch-tests',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0'))),
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.LAUNCH_TESTS]
                  },
              },
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.buildbucket.simulated_get_multi([
          child_build
      ], step_name='RUNNING IN RETRY MODE.verify previous build.get child builder data'
                                         ),
      api.buildbucket.simulated_get_multi([
          child_build
      ], step_name='run builds.(RETRY-MODE) not retrying RUN_CHILDREN.buildbucket.get_multi'
                                         ),
      api.post_check(
          post_process.MustRun,
          'set up orchestrator.(RETRY-MODE) not retrying CREATE_BUILDSPEC'),
      api.post_check(post_process.MustRun,
                     'run builds.(RETRY-MODE) not retrying RUN_CHILDREN'),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True,
          schedule_public_build=True),
      builder='release-main-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
  )

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'orchestrator'
  original_build.output.properties[
      'buildspec_gs_uri'] = 'gs://chromeos-manifest-versions/foo/1.xml'
  original_build.output.properties['child_builds'] = [
      '8922054662172514002', '8922054662172514003'
  ]

  child_builds = []
  child_build = build_pb2.Build(id=8922054662172514002, status='FAILURE',
                                builder={'builder': 'eve-release-main'})
  child_build.input.properties['recipe'] = 'build_release'
  child_builds.append(child_build)
  child_build = build_pb2.Build(id=8922054662172514003, status='SUCCESS',
                                builder={'builder': 'octopus-release-main'})
  child_build.input.properties['recipe'] = 'build_release'
  child_builds.append(child_build)

  eve_retry = build_pb2.Build(id=8922054662172514002, status='SUCCESS',
                              builder={'builder': 'eve-release-main'})
  eve_retry.input.properties['recipe'] = 'build_release'

  yield api.orch_menu.test(
      'release-orchestrator-retry-run-failed-children',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0'))),
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.RUN_FAILED_CHILDREN]
                  },
                  'builder_exec_steps': {
                      'octopus-release-main': {
                          'steps': [RetryStep.PAYGEN],
                      },
                  }
              },
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'child builds': {},
                  },
              },
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.buildbucket.simulated_get_multi(
          child_builds,
          step_name='RUNNING IN RETRY MODE.verify previous build.get child builder data'
      ),
      api.buildbucket.simulated_get_multi([eve_retry],
                                          step_name='run builds.get'),
      api.post_check(
          post_process.MustRun,
          'set up orchestrator.(RETRY-MODE) not retrying CREATE_BUILDSPEC'),
      api.post_check(
          post_process.DoesNotRun,
          'set up orchestrator.(RETRY-MODE) not retrying RUN_CHILDREN'),
      api.post_check(post_process.MustRun,
                     'run builds.only rerunning failed children'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) previously successful builds'),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True),
      builder='release-main-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
  )

  yield api.orch_menu.test(
      'release-orchestrator-retry-run-failed-children-conductor-disabled',
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0'))),
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.RUN_FAILED_CHILDREN]
                  },
                  'builder_exec_steps': {
                      'octopus-release-main': {
                          'steps': [RetryStep.PAYGEN],
                      },
                  }
              },
              '$chromeos/conductor': {
                  'enable_conductor': False,
                  'collect_configs': {
                      'child builds': {},
                  },
              },
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.buildbucket.simulated_get_multi(
          child_builds,
          step_name='RUNNING IN RETRY MODE.verify previous build.get child builder data'
      ),
      api.post_check(
          post_process.SummaryMarkdown,
          'RUN_FAILED_CHILDREN only works if conductor is enabled in non-dryrun mode.'
      ),
      api.post_process(post_process.DropExpectation),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True),
      builder='release-main-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
      status='FAILURE',
  )

  summary = ('Full version: R99-1234.56.0'
             '\n\n3 out of 3 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:'
             '\n\n- htarget.hw.some-other-suite:')
  yield api.orch_menu.test(
      'release-orchestrator-with-failure',
      data.ctp_failure,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      api.post_check(post_process.StepTextEquals,
                     'set up orchestrator.bump version', ''),
      api.post_check(
          post_process.MustRun,
          'set up orchestrator.create buildspec.upload buildspecs/99/1234.56.0.xml to gs://buildspecbucket/buildspecs/99/1234.56.0.xml'
      ),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main',
          schedule_public_build=True),
      builder='release-main-orchestrator',
      collect_builds=api.orch_menu.orch_child_builds(
          'release-main-orchestrator', '-release-main')[0],
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
      status='FAILURE',
  )

  yield api.orch_menu.test(
      'staging-release-orchestrator',
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0'))),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.schedule public build'),
      api.post_check(post_process.StepTextEquals,
                     'set up orchestrator.bump version', 'dry-run only'),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'}, bump_version=True,
          schedule_public_build=True),
      builder='staging-release-main-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
  )

  # The `release-orchestrator-branched` and
  # `release-orchestrator-branched-failure` tests exist to test uprev
  # functionality (which doesn't happen on ToT), we can discard many of the
  # checks from `release-orchestrator`.
  yield api.orch_menu.test(
      'release-orchestrator-branched',
      data.ctp_normal,
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0')),
      ),
      api.post_check(post_process.StepTextEquals,
                     'set up orchestrator.bump version', ''),
      api.post_check(post_process.StepSuccess,
                     'set up orchestrator.uprev packages'),
      api.post_check(post_process.StepSuccess,
                     'set up orchestrator.push uprevs'),
      api.post_process(post_process.DropExpectation),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main', skip_paygen=True,
          schedule_public_build=True,
          retry_allowlist_qs_account=['release_high_prio'],
          retry_allowlist_build_target=['atlas', 'zork']),
      builder='release-stabilize-15185.B-orchestrator',
      collect_builds=api.orch_menu.orch_child_builds(
          'release-stabilize-15185.B-orchestrator', '-release-main')[0],
      with_manifest_refs=True,
      with_history=True,
      sheriff_rotations=['chromeos'],
      bot_size='medium',
  )

  yield api.orch_menu.test(
      'release-orchestrator-branched-failure',
      api.properties(
          FullProperties(
              is_release_orchestrator=True, use_extra_props=True,
              skip_paygen=True, expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown='Full version: R99-1234.56.0')),
      ),
      api.step_data(
          ('set up orchestrator.push uprevs.push to src/private-overlay.git push src/private-overlay'
          ),
          retcode=1,
      ),
      api.post_check(post_process.StepException,
                     'set up orchestrator.push uprevs'),
      api.post_check(post_process.StepFailure, 'set up orchestrator'),
      api.post_process(post_process.DropExpectation),
      builder='release-stabilize-15185.B-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      sheriff_rotations=['chromeos'],
      bot_size='medium',
      status='FAILURE',
  )

  yield api.orch_menu.test(
      'public-orchestrator',
      api.properties(
          **{
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/108/15156.0.0.xml'
                  }
              }
          }),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.sync to specified manifest'),
      builder='public-main-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      bot_size='medium',
  )

  # TODO(b/245326818): Add useful assertions
  yield api.orch_menu.test(
      'factory-orchestrator',
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'},
          buildspec_gs_path='gs://buildspecbucket/buildspecs/',
          bump_version=True, manifest_versions_branch='main'),
      builder='factory-corsola-15197.B-orchestrator',
      with_history=True,
      bot_size='medium',
  )

  collect, _ = api.orch_menu.orch_child_builds('postsubmit-orchestrator',
                                               '-postsubmit')
  yield api.orch_menu.test(
      'branch', data.ctp_normal, api.cros_source.snapshot_xml_exists(False),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.read git footers'),
      collect_builds=collect, input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'}),
      with_manifest_refs=True, with_history=True)

  summary = ('3 out of 3 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:'
             '\n\n- htarget.hw.some-other-suite:')
  yield api.orch_menu.test(
      'test-failure',
      data.ctp_failure,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      input_properties=orch_menu_properties(
          update_manifest_refs={'test': 'refs/heads/test'}),
      collect_builds=collect,
      with_manifest_refs=True,
      with_history=True,
      status='FAILURE',
  )

  yield api.orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config', with_manifest_refs=True)

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False),
      cq=True,
      with_history=True,
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable-staging-exp',
      api.step_data(
          'cherry-pick gerrit changes.apply gerrit patch sets.git cherry-pick',
          retcode=1),
      api.step_data(
          'cherry-pick gerrit changes.apply gerrit patch sets.git merge',
          retcode=1),
      cq=True,
      builder='staging-cq-orchestrator',
      status='FAILURE',
  )

  one_non_crit_fail_summary = ('1 non-critical build failed')
  collect, collect_after = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')
  # Joins an inflight orchestrator run.
  yield api.orch_menu.test(
      'inflight-orchestrator', data.ctp_normal,
      api.post_check(post_process.MustRun, 'find inflight orchestrator'),
      api.post_check(
          post_process.MustRun,
          'find inflight orchestrator.waiting for existing runs.wait'),
      api.properties(
          FullProperties(
              expected_completed_builds=collect + collect_after,
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary),
              expected_enable_history=True)), cq=True, collect_builds=collect,
      history_builds=data.history_builds, collect_after_builds=collect_after,
      with_history=True, git_footers=[],
      inflight_orch=[data.inflight_orchestrator])

  # Runs when there is no inflight orchestrator.
  yield api.orch_menu.test(
      'no-inflight-orchestrator', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_completed_builds=collect + collect_after,
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary),
              expected_enable_history=True)),
      api.post_check(post_process.DoesNotRun,
                     'find related CLs'), cq=True, collect_builds=collect,
      history_builds=data.history_builds, collect_after_builds=collect_after,
      with_history=True, git_footers=[], inflight_orch=[])

  # Collect times out
  yield api.orch_menu.test(
      'collect-children-timeout', data.ctp_normal,
      api.properties(
          FullProperties(
              expected_recipe_result=RawResult(
                  status=common_pb2.SUCCESS,
                  summary_markdown=one_non_crit_fail_summary))),
      api.step_data('run builds.collect.wait', retcode=1),
      collect_builds=data.builds, history_builds=data.history_builds,
      collect_timeout=True, with_manifest_refs=True, with_history=True)

  yield api.orch_menu.test(
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
  yield api.orch_menu.test(
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
  yield api.orch_menu.test(
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

  collect, collect_after = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')
  # Mark one critical child build as failed in each of the collect steps.
  # TODO(b/279016710): Get clarification on how we should treat unset
  # criticality (apparently cave-cq is not actually critical).
  for b in collect:
    if b.builder.builder == 'atlas-cq':
      b.status = common_pb2.FAILURE
  for b in collect_after:
    if b.builder.builder == 'cave-cq':
      b.status = common_pb2.FAILURE
  summary = ('1 out of 6 builds failed\n\n- atlas-cq: [build page](https://'
             'cr-buildbucket.appspot.com/build/8922054662172514004)')
  yield api.orch_menu.test(
      'critical-child-builder-fails',
      api.properties(
          FullProperties(
              expected_completed_builds=collect + collect_after,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      collect_builds=collect,
      collect_after_builds=collect_after,
      with_manifest_refs=True,
      status='FAILURE',
      cq=True,
      builder='cq-orchestrator',
  )

  collect, collect_after = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')
  # Mark one of the non-critical child builds as a failure.
  for b in collect_after:
    if b.builder.builder == 'coral-cq':
      b.status = common_pb2.FAILURE
  yield api.orch_menu.test(
      'non-critical-child-builder-fails',
      data.ctp_normal,
      api.properties(
          FullProperties(expected_completed_builds=collect + collect_after)),
      collect_builds=collect,
      collect_after_builds=collect_after,
      with_manifest_refs=True,
      builder='cq-orchestrator',
      cq=True,
  )

  input_props = orch_menu_properties(
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
  yield api.orch_menu.test(
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
      collect_builds=api.orch_menu.orch_child_builds('postsubmit-orchestrator',
                                                     '-postsubmit')[0],
      input_properties=input_props_with_generate_ctpv1_format,
      builder='postsubmit-orchestrator',
      with_manifest_refs=True,
      with_history=True,
      extra_changes=gerrit_changes,
  )

  summary = ('3 out of 3 hw tests failed\n\n- htarget.hw.bvt-cq:'
             '\n\n- htarget.hw.bvt-inline:'
             '\n\n- htarget.hw.some-other-suite:')
  yield api.orch_menu.test(
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

  yield api.orch_menu.test(
      'snapshot-orch-v2-test-planning',
      api.buildbucket.simulated_multi_predicates_search_results(
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
      experiments=['chromeos.orch_menu.plan_tests_using_snapshot'],
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

  yield api.orch_menu.test(
      'snapshot-orch-v2-test-planning-annealing-not-found',
      api.expect_exception('RuntimeError'),
      api.post_process(
          post_process.ResultReasonRE,
          'no annealing build found for snapshot_id snapshot-HEAD-SHA'),
      api.post_process(post_process.DropExpectation),
      builder='snapshot-orchestrator',
      experiments=['chromeos.orch_menu.plan_tests_using_snapshot'],
  )
