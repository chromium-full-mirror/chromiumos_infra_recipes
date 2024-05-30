# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from RECIPE_MODULES.chromeos.failures.api import Failure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  results = api.failures.Results(failures=[], successes={})

  failure1 = Failure(kind='test', title='test-a',
                     link_map={'subtest-1': 'test-a.com'}, fatal=True,
                     id='id-1')
  failure2 = Failure(kind='test', title='test-b',
                     link_map={'subtest-2': 'test-b.com'}, fatal=True,
                     id='id-2')
  failure3 = Failure(kind='test', title='test-c',
                     link_map={'subtest-3': 'test-c.com'}, fatal=False,
                     id='id-3')
  success1 = {'test': 100}
  success2 = {'build': 10, 'test': 28}

  results.add_results(
      api.failures.Results(failures=[failure1, failure2], successes=success1))
  results.add_results(api.failures.Results(failures=None, successes=success2))
  results.add_results(api.failures.Results(failures=[failure3], successes=None))

  api.assertions.assertEqual(
      results,
      api.failures.Results(failures=[failure1, failure2, failure3], successes={
          'build': 10,
          'test': 128
      }))


def GenTests(api):
  yield api.test('basic')
