# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.build_report import BuildReport
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure, InfraFailure

DEPS = [
    'recipe_engine/properties',
    'build_reporting',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails


def RunSteps(api):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')
  with api.build_reporting.status_reporting():
    if api.properties['failure'] == 'failure':
      raise StepFailure('failure')

    if api.properties['failure'] == 'infra_failure':
      raise InfraFailure('infra failure')


def GenTests(api):
  yield api.test(
      'pass',
      api.properties(failure='None'),
      api.post_check(post_process.LogContains, 'build status pubsub update',
                     'message', ['RUNNING']),
      api.post_check(post_process.LogContains, 'build status pubsub update (2)',
                     'message', ['SUCCESS']),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'fail',
      api.properties(failure='failure'),
      api.post_check(post_process.LogContains, 'build status pubsub update',
                     'message', ['RUNNING']),
      api.post_check(post_process.LogContains, 'build status pubsub update (2)',
                     'message', ['FAILURE']),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
  yield api.test(
      'infra-fail',
      api.properties(failure='infra_failure'),
      api.post_check(post_process.LogContains, 'build status pubsub update',
                     'message', ['RUNNING']),
      api.post_check(post_process.LogContains, 'build status pubsub update (2)',
                     'message', ['INFRA_FAILURE']),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
