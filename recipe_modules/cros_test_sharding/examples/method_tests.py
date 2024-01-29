# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test against private methods in the cros_test_sharding module"""

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_sharding',
]


PROPERTIES = {
    'shard_count': Property(
        kind=int,
    ),
    'expected_shard_count': Property(
        kind=int,
    ),
    'test_suite_token': Property(
        kind=str,
    )
}


def RunSteps(api, shard_count, expected_shard_count, test_suite_token):
  #  Define some example tests
  test_suite = None
  if test_suite_token == '_gen_generic_test_suites':
    test_suite = _gen_generic_test_suites()
  elif test_suite_token == '_gen_secuirty_test_suites':
    test_suite = _gen_security_test_suites()
  #  Directly test some methods.
  # tests_to_bucket = list(test_suite.test_cases.test_cases)
  shards = api.cros_test_sharding.optimized_shard_allocation(  # pylint: disable=protected-access
      test_suite, test_suite.name, 'any', shard_count)
  api.assertions.assertEqual(len(shards), expected_shard_count)


def GenTests(api):
  yield api.test(
      'zero shard time',
      api.properties(shard_count=2, expected_shard_count=2,
                     test_suite_token='_gen_generic_test_suites'),
  )
  yield api.test(
      'zero shard count',
      api.properties(shard_count=0, expected_shard_count=8,
                     test_suite_token='_gen_generic_test_suites'),
  )
  yield api.test(
      'security only tests',
      api.properties(shard_count=2, expected_shard_count=1,
                     test_suite_token='_gen_secuirty_test_suites'),
  )


#  This is getting out of hand.
#test_suite.test_cases.test_cases.test_case.id.value
# for test_case in test_cases:
#   if 'tast.security' in test_case.id.value:
#  Structure of test_suites
# 'test_suites': [{
#     'name': 'suite1',
#     'test_case_ids': {
#         'test_case_ids': [{
#             'value': 'tauto.stub_Pass'
#         }, {
#             'value': 'tast.example.Fail'
#         }, {
#             'value': 'tast.example.Pass'
#         }]
#     }
# }],


class ID:

  def __init__(self, value):
    self.value = value


class TestCase:
  # TestCase
  def __init__(self, name):
    self.id = ID(name)


class TestCases:

  def __init__(self, tests):
    self.test_cases = []
    for test in tests:
      self.test_cases.append(TestCase(test))


class TestSuite:

  def __init__(self, name, tests):
    self.name = name
    self.test_cases = TestCases(tests)


def _gen_generic_test_suites():
  test_cases = [
      'tauto.stub_Pass',
      'tast.example.One',
      'tast.example.Two',
      'tast.example.Three',
      'tast.example.Four',
      'tast.example.Five',
      'tast.example.Six',
      'tast.security.Pass',
      'tast.security.Fail',
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_security_test_suites():
  test_cases = [
      'tast.security.Pass',
      'tast.security.Fail',
  ]
  return TestSuite('bvt-generic-security', test_cases)
