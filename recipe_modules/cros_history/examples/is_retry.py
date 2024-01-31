# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]



def RunSteps(api):
  api.assertions.assertEqual(api.cros_history.is_retry,
                             api.properties['is_retry'])


def GenTests(api):

  yield api.test('basic', api.properties(is_retry=False))

  yield api.test(
      'is-retry',
      api.buildbucket.simulated_search_results([
          api.buildbucket.try_build_message(project='chromeos', bucket='cq',
                                            builder='bojack-cq',
                                            status='SUCCESS', build_id=123)
      ], 'find matching builds.buildbucket.search'),
      api.properties(is_retry=True))

  yield api.test('test-value', api.cros_history.is_retry(True),
                 api.properties(is_retry=True))
