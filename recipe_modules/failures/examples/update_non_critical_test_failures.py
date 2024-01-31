# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  test_plan_summary = {
      'critical-test': True,
      'newly-critical-test': True,
      'non-critical-test': False,
      'newly-non-critical-test': False,
  }

  initial_failures = [
      # Test criticality is disabled for deleted tests.
      api.failures.Failure(kind='test', title='deleted-test', link_map={},
                           fatal=True, id='deleted-test'),
      # Test criticality is disabled for newly non-critical tests.
      api.failures.Failure(kind='test', title='newly-non-critical-test',
                           link_map={}, fatal=True,
                           id='newly-non-critical-test'),
      # Test criticality isn't enabled for newly critical tests.
      api.failures.Failure(kind='test', title='newly-critical-test',
                           link_map={}, fatal=False, id='newly-critical-test'),
      # Test build failures aren't be updated.
      api.failures.Failure(kind='build', title='title', link_map={}, fatal=True,
                           id='critical builder'),
      # Test failures aren't updated if criticality hasn't changed.
      api.failures.Failure(kind='test', title='critical-test', link_map={},
                           fatal=True, id='critical-test'),
      api.failures.Failure(kind='test', title='non-critical-test', link_map={},
                           fatal=False, id='non-critical-test'),
  ]
  expected_failures = [
      api.failures.Failure(kind='test', title='deleted-test', link_map={},
                           fatal=True, id='deleted-test'),
      api.failures.Failure(kind='test', title='newly-non-critical-test',
                           link_map={}, fatal=False,
                           id='newly-non-critical-test'),
      api.failures.Failure(kind='test', title='newly-critical-test',
                           link_map={}, fatal=False, id='newly-critical-test'),
      api.failures.Failure(kind='build', title='title', link_map={}, fatal=True,
                           id='critical builder'),
      api.failures.Failure(kind='test', title='critical-test', link_map={},
                           fatal=True, id='critical-test'),
      api.failures.Failure(kind='test', title='non-critical-test', link_map={},
                           fatal=False, id='non-critical-test'),
  ]

  updated_failures = api.failures.update_non_critical_test_failures(
      initial_failures, test_plan_summary)
  api.assertions.assertCountEqual(expected_failures, updated_failures)


def GenTests(api):
  yield api.test('basic')
