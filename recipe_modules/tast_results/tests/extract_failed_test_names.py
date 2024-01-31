# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'tast_results',
]



def RunSteps(api):
  failed_test_names = api.tast_results.extract_failed_test_names(
      api.buildbucket.build)
  api.assertions.assertCountEqual(
      failed_test_names, api.properties.get('expected_failed_test_names', []))


def GenTests(api):

  def _build_msg(failed_test_names=None):
    msg = api.buildbucket.try_build_message()
    if failed_test_names is None:
      return msg

    failed_test_cases = [{
        'name': name,
        'verdict': 'VERDICT_FAILED'
    } for name in failed_test_names]
    msg.output.properties.update({'failed_test_cases': failed_test_cases})
    return msg

  yield api.test(
      'no-failed-test-cases-prop',
      api.buildbucket.build(_build_msg()),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failed-test-cases-empty',
      api.buildbucket.build(_build_msg(failed_test_names=[])),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'some-failed-test-cases',
      api.buildbucket.build(_build_msg(failed_test_names=['test1', 'test2'])),
      api.properties(expected_failed_test_names=['test1', 'test2']),
      api.post_process(post_process.DropExpectation),
  )
