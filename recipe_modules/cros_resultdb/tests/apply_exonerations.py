# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.recipe_modules.chromeos.cros_resultdb.tests.test import (
    TestInputProperties)
from PB.test_platform.request import Request

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/resultdb',
    'recipe_engine/properties',
    'cros_resultdb',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.cros_resultdb.apply_exonerations(
      [api.cros_resultdb.current_invocation_id],
      default_behavior=properties.default_behavior,
      behavior_overrides_map=properties.behavior_overrides_map,
      variant_filter=properties.variant_filter)


def GenTests(api):

  variant_json = api.json.dumps({'def': {'board': 'fake-board'}})

  inv_bundle = {
      'build:123':
          api.resultdb.Invocation(test_results=[
              test_result_pb2.TestResult(
                  test_id='test/1', expected=False,
                  status=test_result_pb2.FAIL, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
              test_result_pb2.TestResult(
                  test_id='test/2', expected=False,
                  status=test_result_pb2.SKIP, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
          ]),
  }

  yield api.test(
      'not-enabled',
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

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
      api.properties(
          behavior_overrides_map={
              'test/1': Request.Params.TestExecutionBehavior.NON_CRITICAL
          }, variant_filter={'board': 'fake-board'}),
      api.post_process(
          post_process.StepSuccess,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'no-matching-exoneration-behavior',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(
          behavior_overrides_map={
              'test/3': Request.Params.TestExecutionBehavior.NON_CRITICAL
          }, variant_filter={'board': 'fake-board'}),
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'no-matching-exoneration-variant-filter',
      api.buildbucket.try_build(build_id=123),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate ResultDB results.rdb query'),
      api.properties(
          behavior_overrides_map={
              'test/1': Request.Params.TestExecutionBehavior.NON_CRITICAL
          }, variant_filter={'board': 'another-fake-board'}),
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )
