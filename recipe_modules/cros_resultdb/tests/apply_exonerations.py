# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.recipe_modules.chromeos.cros_resultdb.tests.test import (
    TestInputProperties)
from PB.test_platform.request import Request

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/resultdb',
    'recipe_engine/properties',
    'cros_resultdb',
]

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.cros_resultdb.apply_exonerations(
      [api.cros_resultdb.current_invocation_id],
      default_behavior=properties.default_behavior,
      behavior_overrides_map=properties.behavior_overrides_map)


def GenTests(api):

  inv_bundle = {
      'build:123':
          api.resultdb.Invocation(test_results=[
              test_result_pb2.TestResult(
                  test_id='test/1',
                  expected=False,
                  status=test_result_pb2.FAIL,
              ),
          ]),
  }

  yield api.test(
      'basic',
      api.buildbucket.try_build(build_id=123),
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'rdb-failure',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(
          default_behavior=Request.Params.TestExecutionBehavior.NON_CRITICAL),
      api.step_data(
          'exonerate ResultDB results.exonerate non-critical failures',
          retcode=1),
      api.step_data('exonerate ResultDB results.rdb query (2)', retcode=1),
      api.post_process(post_process.StepWarning, 'exonerate ResultDB results'),
  )

  yield api.test(
      'rdb-failure-succeed-on-retry',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(
          default_behavior=Request.Params.TestExecutionBehavior.NON_CRITICAL),
      api.step_data(
          'exonerate ResultDB results.exonerate non-critical failures',
          retcode=1),
      api.post_process(post_process.StepWarning, 'exonerate ResultDB results'),
  )

  yield api.test(
      'default-non-critical',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(
          default_behavior=Request.Params.TestExecutionBehavior.NON_CRITICAL),
      api.post_process(
          post_process.StepSuccess,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'test-override-non-critical',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(behavior_overrides_map={
          'test/1': Request.Params.TestExecutionBehavior.NON_CRITICAL
      }),
      api.post_process(
          post_process.StepSuccess,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'no-matching-exoneration',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(behavior_overrides_map={
          'test/2': Request.Params.TestExecutionBehavior.NON_CRITICAL
      }),
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )
