# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  hw_tests = [
      HwTestCfg.HwTest(
          common=TestSuiteCommon(
              display_name='my_build_target.hw.my_test_suite',
              critical={'value': True}),
          suite='my_test_suite',
          skylab_board='my_board',
          pool='DUT_POOL_QUOTA',
          hw_test_suite_type=HwTestCfg.TAST,
      ),
      HwTestCfg.HwTest(
          common=TestSuiteCommon(display_name='build_target.hw.my_test_suite',
                                 critical={'value': False}),
          suite='my_test_suite',
          skylab_board='board',
          pool='DUT_POOL_QUOTA',
          hw_test_suite_type=HwTestCfg.TAST,
      )
  ]
  failures = api.failures.get_additional_hw_test_not_run_failures(hw_tests)
  expected_failures = [
      api.failures.Failure('additional test not run',
                           'my_build_target.hw.my_test_suite', {}, True,
                           'my_build_target.hw.my_test_suite'),
  ]
  #len is 1 since the non critical test is not returned as failures
  api.assertions.assertEqual(len(failures), 1)
  api.assertions.assertEqual(failures, expected_failures)


def GenTests(api):
  yield api.test('basic')
