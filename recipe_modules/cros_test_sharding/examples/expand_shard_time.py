# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test against public methods in the cros_test_sharding module"""

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_sharding',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'shard_count': Property(
        kind=int,
    ),
}


def RunSteps(api, shard_count):
  total_shards = shard_count
  #  Define some example tests
  test_suite = _gen_generic_test_suites()
  #  Generate the shards
  shards = api.cros_test_sharding.optimized_shard_allocation(
      test_suite, total_shards)

  api.assertions.assertEqual(len(shards), 4)


def GenTests(api):
  yield api.test(
      'zero shards',
      api.properties(shard_count=0),
  )

  yield api.test(
      '10 shards',
      api.properties(shard_count=10),
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

  def __init__(self, tests):
    self.test_cases = TestCases(tests)


def _gen_generic_test_suites():
  test_cases = [
      'tauto.stub_Pass', 'tast.example.Fail', 'tast.example.Pass',
      'tast.security.Pass', 'tast.security.Fail'
  ]
  return TestSuite(test_cases)
