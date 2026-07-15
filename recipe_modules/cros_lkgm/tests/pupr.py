# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the PUpr triggering logic in cros_lkgm module."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_lkgm',
    'cros_tags',
    'greenness',
    'src_state',
    'test_util',
]


def RunSteps(api):
  # 1. Create child builds.
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



def GenTests(api):
  # Helper to generate test cases.
  def build_test(name, enable_pupr, test_failed_builds, expected_pupr_triggered,
                 builder='release-main-orchestrator', no_builds=False,
                 custom_pupr_builder_name='cros_lkgm.pupr', extra_checks=None):
    # Prepare properties.
    lkgm_props = {
        'enable_lkgm': True,
        'enable_pupr': enable_pupr,
        'builder_threshold_percentage': 50,
    }
    if custom_pupr_builder_name:
      lkgm_props['pupr_builder_name'] = custom_pupr_builder_name

    props = {
        '$chromeos/greenness': {
            'publish_property': True,
        },
        '$chromeos/cros_lkgm': lkgm_props,
        'test_failed_builds': test_failed_builds,
        'no_builds': no_builds,
        'some_arbitrary_input_prop': 'hello-world',
    }

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
                   expected_pupr_triggered=False)
  yield build_test('pupr-enabled-green', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=True)
  yield build_test('pupr-enabled-not-green', enable_pupr=True,
                   test_failed_builds=True, expected_pupr_triggered=False)
  yield build_test('pupr-enabled-no-builds', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=False,
                   no_builds=True)
  yield build_test('pupr-enabled-staging', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=True,
                   builder='staging-release-main-orchestrator')
  yield build_test('pupr-enabled-no-name', enable_pupr=True,
                   test_failed_builds=False, expected_pupr_triggered=False,
                   custom_pupr_builder_name="")

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
