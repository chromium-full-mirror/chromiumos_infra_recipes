# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for setting package failures."""

from google.protobuf import json_format

from PB.chromiumos.common import PackageInfo
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFailureAttribute
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'image_builder_failures',
    'test_util',
]



def RunSteps(api):

  with api.step.nest('no failures') as test_step:
    # Call with no failed packages, should noop.
    api.image_builder_failures.set_compile_failed_packages(test_step, [])
    api.image_builder_failures.set_test_failed_packages(test_step, [])

  package_info_0 = PackageInfo(package_name='package-name', category='category')
  package_info_1 = PackageInfo(package_name='package1')
  package_info_2 = PackageInfo(package_name='package2')
  package_info_3 = PackageInfo(package_name='package3')
  package_info_4 = PackageInfo(package_name='package4')
  package_info_5 = PackageInfo(package_name='package')

  with api.step.nest('one compile failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed compilation for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_compile_failure/category_package-name_log\)',
        api.image_builder_failures.set_compile_failed_packages, test_step,
        [(package_info_0, 'test log')])

  with api.step.nest('one compile failure with attribution') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed compilation for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_compile_failure_with_attribution/category_package-name_log\)',
        api.image_builder_failures.set_compile_failed_packages, test_step,
        [(package_info_0, 'test log')], cl_affected_packages=[package_info_0])

  with api.step.nest(
      'one compile failure with snapshot comparison') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed compilation for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_compile_failure_with_snapshot_comparison/category_package-name_log\)',
        api.image_builder_failures.set_compile_failed_packages, test_step,
        [(package_info_0, 'test log')])

  with api.step.nest('one test failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed unit tests for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_test_failure/category_package-name_log\)',
        api.image_builder_failures.set_test_failed_packages, test_step,
        [(package_info_0, 'test log')])

  with api.step.nest('one test failure with attribution') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed unit tests for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_test_failure_with_attribution/category_package-name_log\)',
        api.image_builder_failures.set_test_failed_packages, test_step,
        [(package_info_0, 'test log')], cl_affected_packages=[package_info_0])

  with api.step.nest('multiple compile failures') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.image_builder_failures.set_compile_failed_packages,
                                test_step,
                                [(package_info_1, 'test log for package1'),
                                 (package_info_2, 'test log for package2')])

  with api.step.nest('multiple test failures') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.image_builder_failures.set_test_failed_packages,
                                test_step,
                                [(package_info_3, 'test log for package3'),
                                 (package_info_4, 'test log for package4')])

  with api.step.nest('test3') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.image_builder_failures.set_compile_failed_packages,
                                test_step, [(package_info_5, '')])

  expected_failures = [
      PackageFailure(package=package_info_0, phase='COMPILE'),
      PackageFailure(package=package_info_0, phase='COMPILE',
                     affected_by_changes=True),
      PackageFailure(package=package_info_0, phase='TEST'),
      PackageFailure(package=package_info_0, phase='TEST',
                     affected_by_changes=True),
      PackageFailure(package=package_info_1, phase='COMPILE'),
      PackageFailure(package=package_info_2, phase='COMPILE'),
      PackageFailure(package=package_info_3, phase='TEST'),
      PackageFailure(package=package_info_4, phase='TEST'),
      PackageFailure(package=package_info_5, phase='COMPILE'),
  ]
  snapshot_comparison_failure = PackageFailure(package=package_info_0,
                                               phase='COMPILE')
  if api.buildbucket.build.builder.builder.endswith('-cq'):
    snapshot_comparison_failure.snapshot_comparison = CqFailureAttribute.MATCHING_FAILURE_FOUND
  expected_failures.append(snapshot_comparison_failure)

  api.assertions.assertCountEqual(api.image_builder_failures.package_failures,
                                  expected_failures)

def GenTests(api):
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test('basic', api.buildbucket.build(build_message))

  cq_build_message = api.buildbucket.ci_build_message(build_id=123,
                                                      builder='atlas-cq')
  cq_build_message.infra.logdog.hostname = 'logs.chromium.org'
  cq_build_message.infra.logdog.project = 'chromeos'
  cq_build_message.infra.logdog.prefix = 'logdog/prefix'
  snapshot_build = api.test_util.test_child_build(
      'atlas', builder_name='atlas-snapshot', output_properties={
          'package_failures': [
              json_format.MessageToDict(
                  PackageFailure(
                      package=PackageInfo(package_name='package-name',
                                          category='category'),
                      phase='COMPILE'))
          ]
      }).message
  yield api.test(
      'cq-child-build',
      api.buildbucket.build(cq_build_message),
      # Failure when trying to compare to snapshot does not fail the build.
      api.step_data('one compile failure with attribution.buildbucket.search',
                    api.raw_io.stream_output_text('there was a problem'),
                    retcode=1),
      api.buildbucket.simulated_search_results(
          [snapshot_build],
          'one compile failure with snapshot comparison.buildbucket.search'))
