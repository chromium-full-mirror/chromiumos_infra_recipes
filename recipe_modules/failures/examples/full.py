# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'failures',
    'test_plan',
]

from PB.recipe_modules.chromeos.failures.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties

from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api, properties):
  api.failures.raise_failed_packages([])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_packages,
                              [PackageInfo(package_name='package')])

  task_results = api.swarming.collect(
      'collect test results.vm_swarming_server.com', ['task'])
  api.failures.verify_tests(task_results)

  api.failures.verify_builds(properties.builds)


def GenTests(api):
  yield api.test('basic')

  yield (api.test('with_verify_task_result_success') +
         api.test_plan.simulated_collect_output('collect test results',
                                                failure=False))

  yield (api.test('with_verify_task_result_failure') +
         api.test_plan.simulated_collect_output('collect test results',
                                                failure=True))

  yield (api.test('with_verify_builds_empty') +
         api.properties(TestInputProperties(builds=[])))

  build = build_pb2.Build(
      builder=build_pb2.BuilderID(project='foo', bucket='bar', builder='baz'),
      id=202, status=common_pb2.SUCCESS, critical=common_pb2.YES)

  yield (api.test('with_verify_builds_success') +
         api.properties(TestInputProperties(builds=[build])))

  build.status = common_pb2.FAILURE

  yield (api.test('with_verify_builds_failure') +
         api.properties(TestInputProperties(builds=[build])))

  build.critical = common_pb2.NO

  yield (api.test('with_verify_builds_failure_but_not_critical') +
         api.properties(TestInputProperties(builds=[build])))
