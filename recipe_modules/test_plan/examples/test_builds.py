# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/properties', 'recipe_engine/step', 'test_plan']


def RunSteps(api):
  # TODO(yshaul): Add build_report and dep_graph when available.
  builder = api.properties['builder']
  build_config = api.properties['build_config']

  try:
    api.test_plan.test_builds('test_non-deferred', builder)
  except:
    # Don't fail the test on exception - we have more to do.
    # Observing the exception in the json output is sufficient.
    pass

  with api.step.defer_results():
    api.test_plan.test_builds('test_deferred', builder)


def GenTests(api):
  builder = 'builder'
  build_config = [dict(build_target='build_target')]
  yield (api.test('basic') + api.properties(builder=builder,
                                            build_config=build_config) +
         api.test_plan.simulate_test_builds('test_non-deferred') +
         api.test_plan.simulate_test_builds('test_deferred'))

  yield (api.test('fail_test_builds') + api.properties(
      builder=builder, build_config=build_config) +
         api.test_plan.fail_test_builds('test_non-deferred') +
         api.test_plan.fail_test_builds('test_deferred'))
