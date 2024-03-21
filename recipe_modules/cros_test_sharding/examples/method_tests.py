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
    ),
    'expected_bucket_count': Property(
        kind=int,
    ),
    'bucket_shard_count': Property(
        kind=int,
    ),
}


def RunSteps(api, shard_count, expected_shard_count, test_suite_token,
             expected_bucket_count, bucket_shard_count):
  #  Define some example tests
  test_suite = None
  if test_suite_token == '_gen_generic_test_suites':
    test_suite = _gen_generic_test_suites()
  elif test_suite_token == '_gen_secuirty_test_suites':
    test_suite = _gen_security_test_suites()
  elif test_suite_token == '_gen_equal_deps_test_suites':
    test_suite = _gen_equal_deps_test_suites()
  elif test_suite_token == '_gen_unequal_deps_test_suites':
    test_suite = _gen_unequal_deps_test_suites()
  elif test_suite_token == '_gen_equal_three_deps_test_suites':
    test_suite = _gen_equal_three_deps_test_suites()
  elif test_suite_token == '_gen_unequal_three_deps_test_suites':
    test_suite = _gen_unequal_three_deps_test_suites()
  elif test_suite_token == '_gen_leftover_eight_deps_test_suites':
    test_suite = _gen_leftover_eight_deps_test_suites()

  #  Bucket deps
  buckets = api.cros_test_sharding.bucket_by_dependencies(
      test_suite.test_cases.test_cases, test_suite.name)
  api.assertions.assertEqual(
      expected_bucket_count, len(buckets),
      msg=f'expected_bucket_count: {expected_bucket_count}, len(buckets): {len(buckets)}'
  )

  #  Deps Shard Buckets
  bucket_shards = api.cros_test_sharding.optimized_shard_allocation_deps(
      buckets, test_suite.name, 'any', shard_count)
  api.assertions.assertEqual(
      len(bucket_shards), bucket_shard_count,
      msg=f'len(bucket_shards), bucket_shard_count; bucket_shards: {bucket_shards}, expected bucket_shard_count is wrong '
  )

  #  Traditional Shard Test
  shards = api.cros_test_sharding.optimized_shard_allocation(
      test_suite, test_suite.name, 'any', shard_count)
  api.assertions.assertEqual(
      len(shards), expected_shard_count,
      msg=f'len(shards): {len(shards)} , expected shards count: {expected_shard_count}'
  )


# shard_count : The number of shards to request
# expected_shard_count : ignoring deps, this is the number of shards that will be produced
# expected_bucket_count : The number of dep buckets that will be generated
# bucket_shard_count : accounting for deps, this is the number of shards that will be produced
#  based on the dep buckets
# test_suite_token : the test suite to use


def GenTests(api):
  yield api.test(
      'limit shard count',
      api.properties(shard_count=2, expected_shard_count=2,
                     expected_bucket_count=3, bucket_shard_count=3,
                     test_suite_token='_gen_generic_test_suites'),
  )
  yield api.test(
      'zero shard count',
      api.properties(shard_count=0, expected_shard_count=8,
                     expected_bucket_count=3, bucket_shard_count=9,
                     test_suite_token='_gen_generic_test_suites'),
  )
  yield api.test(
      'security only tests',
      api.properties(shard_count=0, expected_shard_count=1,
                     expected_bucket_count=1, bucket_shard_count=2,
                     test_suite_token='_gen_secuirty_test_suites'),
  )
  yield api.test(
      'equal deps',
      api.properties(shard_count=0, expected_shard_count=10,
                     expected_bucket_count=2, bucket_shard_count=10,
                     test_suite_token='_gen_equal_deps_test_suites'))
  yield api.test(
      'unequal deps',
      api.properties(shard_count=10, expected_shard_count=9,
                     expected_bucket_count=2, bucket_shard_count=9,
                     test_suite_token='_gen_unequal_deps_test_suites'))
  yield api.test(
      'equal three deps',
      api.properties(shard_count=10, expected_shard_count=9,
                     expected_bucket_count=3, bucket_shard_count=9,
                     test_suite_token='_gen_equal_three_deps_test_suites'))
  yield api.test(
      'unequal three deps',
      api.properties(shard_count=10, expected_shard_count=10,
                     expected_bucket_count=3, bucket_shard_count=10,
                     test_suite_token='_gen_unequal_three_deps_test_suites'))

  yield api.test(
      'eight suite tests',
      api.properties(shard_count=10, expected_shard_count=10,
                     expected_bucket_count=4, bucket_shard_count=8,
                     test_suite_token='_gen_leftover_eight_deps_test_suites'))


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


class Dependency:

  def __init__(self, value):
    self.value = value


class TestCase:
  # TestCase
  def __init__(self, test):
    self.id = ID(test['name'])
    self.dependencies = [Dependency(dep) for dep in test['deps']]


class TestCases:

  def __init__(self, tests):
    self.test_cases = [TestCase(test) for test in tests]


class TestSuite:

  def __init__(self, name, tests):
    self.name = name
    self.test_cases = TestCases(tests)


def _gen_generic_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [1]
      },
      {
          'name': 'tast.example.Four',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.security.Pass',
          'deps': [2]
      },
      {
          'name': 'tast.security.Fail',
          'deps': [2]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_equal_deps_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [1]
      },
      {
          'name': 'tast.example.Four',
          'deps': [1]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_unequal_deps_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [1]
      },
      {
          'name': 'tast.example.Four',
          'deps': [1]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [2]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_equal_three_deps_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [2]
      },
      {
          'name': 'tast.example.Four',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [3]
      },
      {
          'name': 'tast.example.Six',
          'deps': [3]
      },
      {
          'name': 'tast.example.Six',
          'deps': [3]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_unequal_three_deps_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [2]
      },
      {
          'name': 'tast.example.Four',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [3]
      },
      {
          'name': 'tast.example.Seven',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_leftover_eight_deps_test_suites():
  test_cases = [
      {
          'name': 'tauto.stub_Pass',
          'deps': [1]
      },
      {
          'name': 'tast.example.One',
          'deps': [1]
      },
      {
          'name': 'tast.example.Two',
          'deps': [1]
      },
      {
          'name': 'tast.example.Three',
          'deps': [1]
      },
      {
          'name': 'tast.example.Four',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Five',
          'deps': [2]
      },
      {
          'name': 'tast.example.Six',
          'deps': [3]
      },
      {
          'name': 'tast.example.Seven',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [3]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [4]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [4]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [4]
      },
      {
          'name': 'tast.example.Eight',
          'deps': [4]
      },
  ]
  return TestSuite('bvt-generic', test_cases)


def _gen_security_test_suites():
  test_cases = [
      {
          'name': 'tast.security.Pass',
          'deps': [1]
      },
      {
          'name': 'tast.security.Fail',
          'deps': [1]
      },
  ]
  return TestSuite('bvt-generic-security', test_cases)
