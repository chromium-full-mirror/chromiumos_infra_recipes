# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the PUpr triggering logic in cros_lkgm module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_lkgm',
    'cros_tags',
    'greenness',
    'src_state',
    'test_util',
]


def RunSteps(api):
  # 1. Create child builds.
  if api.properties.get('custom_builds'):
    builds = [
        api.test_util.test_api.test_child_build(
            builder=b['builder'], build_target_name='target', critical='YES',
            status=b.get('status', 'SUCCESS'), tags=api.cros_tags.tags(**{
                'relevance': b.get('relevance', 'relevant'),
            })).message for b in api.properties['custom_builds']
    ]
  else:
    builds = [
        api.test_util.test_api.test_child_build(
            builder='eve-snapshot', build_target_name='eve', critical='YES',
            status='SUCCESS', tags=api.cros_tags.tags(**{
                'relevance': 'relevant',
            })).message,
    ]

  if api.properties.get('test_failed_builds'):
    for build in builds:
      build.status = 20

  if api.properties.get('no_builds'):
    builds = []

  api.greenness.update_build_info(builds)

  gitiles_commit = api.src_state.gitiles_commit

  if api.properties.get('mock_greenness_failure'):
    orig_prop = type(api.greenness).builder_greenness_dict
    try:
      type(api.greenness).builder_greenness_dict = property(lambda self: 1 / 0)
      api.cros_lkgm.do_lkgm_via_pupr(gitiles_commit)
    finally:
      type(api.greenness).builder_greenness_dict = orig_prop
  else:
    api.cros_lkgm.do_lkgm_via_pupr(gitiles_commit)

  if 'expected_lkgm_skipped_reason' in api.properties:
    api.assertions.assertEqual(
        api.cros_lkgm.lkgm_skipped_reason,
        api.properties['expected_lkgm_skipped_reason'],
    )



def GenTests(api):
  # Helper to generate test cases.
  def build_test(name, enable_pupr, test_failed_builds, expected_pupr_triggered,
                 builder='release-main-orchestrator', no_builds=False,
                 custom_pupr_builder_name='cros_lkgm.pupr',
                 required_green_builders=None, custom_builds=None,
                 builder_threshold_percentage=50,
                 expected_lkgm_skipped_reason=None, extra_checks=None):
    # Prepare properties.
    lkgm_props = {
        'enable_lkgm': True,
        'enable_pupr': enable_pupr,
        'builder_threshold_percentage': builder_threshold_percentage,
    }
    if custom_pupr_builder_name:
      lkgm_props['pupr_builder_name'] = custom_pupr_builder_name
    if required_green_builders is not None:
      lkgm_props['required_green_builders'] = required_green_builders

    props = {
        '$chromeos/greenness': {
            'publish_property': True,
        },
        '$chromeos/cros_lkgm': lkgm_props,
        'test_failed_builds': test_failed_builds,
        'no_builds': no_builds,
        'some_arbitrary_input_prop': 'hello-world',
    }
    if expected_lkgm_skipped_reason is not None:
      props['expected_lkgm_skipped_reason'] = expected_lkgm_skipped_reason
    if custom_builds:
      props['custom_builds'] = custom_builds

    if custom_pupr_builder_name:
      job_base_name = custom_pupr_builder_name
      if 'staging' in builder:
        job_name = job_base_name if job_base_name.startswith(
            'staging-') else f'staging-{job_base_name}'
      else:
        job_name = job_base_name
    else:
      job_name = 'cros_lkgm.pupr'

    step_name = f'do lkgm via pupr.trigger {job_name}'

    checks = []
    if expected_pupr_triggered:
      checks.append(api.post_check(post_process.MustRun, step_name))
      # Verify properties are passed.
      checks.append(
          api.post_check(post_process.LogContains, step_name, 'input', [
              '"triggers": [',
              '"gitiles": {',
              '"repo": "https://chromium.googlesource.com/project-a"',
              '"ref": "refs/heads/main"',
              '"revision": "2d72510e447ab60a9728aeea2362d8be2cbd7789"',
          ]))
    else:
      checks.append(api.post_check(post_process.DoesNotRun, step_name))

    if extra_checks:
      checks.extend(extra_checks)

    return api.test(
        name,
        api.test_util.test_orchestrator(bucket='release',
                                        builder=builder).build,
        api.properties(**props),
        *checks,
        api.post_process(post_process.DropExpectation),
    )

  # Test cases:
  yield build_test('pupr-disabled', enable_pupr=False, test_failed_builds=False,
                   expected_pupr_triggered=False,
                   expected_lkgm_skipped_reason='PUpr is not enabled')
  yield build_test('pupr-enabled-green', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=True)
  yield build_test(
      'pupr-enabled-not-green', enable_pupr=True, test_failed_builds=True,
      expected_pupr_triggered=False,
      expected_lkgm_skipped_reason='aggregated greenness: 0.00%, threshold: 50% (below threshold)'
  )
  yield build_test(
      'pupr-enabled-no-builds', enable_pupr=True, test_failed_builds=False,
      expected_pupr_triggered=False, no_builds=True,
      expected_lkgm_skipped_reason='aggregated greenness: 0.00%, threshold: 50% (below threshold)'
  )
  yield build_test('pupr-enabled-staging', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=True,
                   builder='staging-release-main-orchestrator')
  yield build_test(
      'pupr-enabled-no-name', enable_pupr=True, test_failed_builds=False,
      expected_pupr_triggered=False, custom_pupr_builder_name='',
      expected_lkgm_skipped_reason='no PUpr builder name configured')

  yield build_test(
      'pupr-custom-builder', enable_pupr=True, test_failed_builds=False,
      expected_pupr_triggered=True, custom_pupr_builder_name='custom-pupr-job',
      extra_checks=[
          api.post_check(post_process.LogContains,
                         'do lkgm via pupr.trigger custom-pupr-job', 'input', [
                             '"project": "chromeos"',
                             '"job": "custom-pupr-job"',
                         ]),
      ])

  yield build_test(
      'pupr-required-builders-all-green', enable_pupr=True,
      test_failed_builds=False, expected_pupr_triggered=True,
      required_green_builders=['eve-snapshot'], custom_builds=[{
          'builder': 'eve-snapshot',
          'status': 'SUCCESS',
          'relevance': 'relevant'
      }])

  yield build_test(
      'pupr-required-builders-not-green', enable_pupr=True,
      test_failed_builds=False, expected_pupr_triggered=False,
      required_green_builders=['eve-snapshot',
                               'kevin-snapshot'], custom_builds=[
                                   {
                                       'builder': 'eve-snapshot',
                                       'status': 'FAILURE',
                                       'relevance': 'relevant'
                                   },
                                   {
                                       'builder': 'kevin-snapshot',
                                       'status': 'FAILURE',
                                       'relevance': 'relevant'
                                   },
                               ], builder_threshold_percentage=0,
      expected_lkgm_skipped_reason='required builders not green: {eve,kevin}-snapshot',
      extra_checks=[
          api.post_check(post_process.StepTextContains, 'do lkgm via pupr',
                         ['required builders not green: {eve,kevin}-snapshot'])
      ])

  last_snapshot_output = build_pb2.Build.Output()
  last_snapshot_output.properties['greenness'] = {
      'builderGreenness': [
          {
              'buildMetric': '100',
              'metric': '100',
              'builder': 'eve-snapshot',
          },
          {
              'buildMetric': '100',
              'metric': '100',
              'builder': 'kevin-snapshot',
          },
      ]
  }
  last_snapshot_build = build_pb2.Build(
      id=123, status=common_pb2.SUCCESS, output=last_snapshot_output,
      input=build_pb2.Build.Input(
          gitiles_commit=common_pb2.GitilesCommit(id='ababab')))

  yield build_test(
      'pupr-required-builders-none-relevant', enable_pupr=True,
      test_failed_builds=False, expected_pupr_triggered=False,
      required_green_builders=['eve-snapshot',
                               'kevin-snapshot'], custom_builds=[
                                   {
                                       'builder': 'eve-snapshot',
                                       'status': 'SUCCESS',
                                       'relevance': 'not relevant',
                                   },
                                   {
                                       'builder': 'kevin-snapshot',
                                       'status': 'SUCCESS',
                                       'relevance': 'not relevant',
                                   },
                               ], builder_threshold_percentage=0,
      expected_lkgm_skipped_reason='at least one required builder in {eve,kevin}-snapshot needs to be relevant',
      extra_checks=[
          api.buildbucket.simulated_search_results(
              builds=[last_snapshot_build],
              step_name='getting last snapshot greenness.buildbucket.search'),
          api.step_data('getting last snapshot greenness.last snapshot.git log',
                        api.raw_io.stream_output_text('ababab\n')),
          api.post_check(post_process.StepTextContains, 'do lkgm via pupr', [
              'at least one required builder in {eve,kevin}-snapshot needs to be relevant'
          ]),
      ])

  yield build_test(
      'pupr-required-builders-missing', enable_pupr=True,
      test_failed_builds=False, expected_pupr_triggered=False,
      required_green_builders=['missing-snapshot'], extra_checks=[
          api.post_check(post_process.StepTextContains, 'do lkgm via pupr',
                         ['required builders not green: missing-snapshot'])
      ])

  yield build_test(
      'pupr-trigger-fails', enable_pupr=True, test_failed_builds=False,
      expected_pupr_triggered=True, extra_checks=[
          api.step_data('do lkgm via pupr.trigger cros_lkgm.pupr', retcode=1),
          api.post_check(post_process.StepFailure, 'do lkgm via pupr'),
          api.post_check(post_process.StepTextContains, 'do lkgm via pupr', [
              'failed: Infra Failure: Step(\'do lkgm via pupr.trigger cros_lkgm.pupr\')'
          ]),
      ])

  yield build_test(
      'pupr-assessment-fails', enable_pupr=True, test_failed_builds=False,
      expected_pupr_triggered=False, extra_checks=[
          api.properties(mock_greenness_failure=True),
          api.post_check(post_process.StepFailure, 'do lkgm via pupr'),
          api.post_check(post_process.StepTextContains, 'do lkgm via pupr',
                         ['failed: division by zero']),
      ])
