# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
]



def RunSteps(api):
  api.assertions.assertCountEqual(api.cros_history.get_passed_tests(),
                                  ['nami/hw/bvt-cq'])

  # Call it again to test the path where it returns the cached value.
  _ = api.cros_history.get_passed_tests()


def GenTests(api):
  yield api.test(
      'has-passed-tests',
      api.buildbucket.simulated_multi_predicates_search_results(
          [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])],
          'get change test history.find matching builds.buildbucket.search'),
      api.post_check(post_process.DoesNotRun, 'get change test history (2)'))
