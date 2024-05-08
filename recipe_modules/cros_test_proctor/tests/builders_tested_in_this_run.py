# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_proctor',
    'cros_test_plan',
]



def RunSteps(api):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  _ = api.cros_test_proctor.schedule_tests(test_plan, [], [],
                                           api.cros_test_proctor.timeout,
                                           snapshot)
  api.assertions.assertCountEqual(
      api.cros_test_proctor.builders_tested_in_this_run,
      api.properties['expected_tested_builders'])


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(expected_tested_builders=['test-builder']),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'test-value-override',
      api.properties(
          expected_tested_builders=['builder-cq', 'another-builder-cq']),
      api.cros_test_proctor.builders_tested_in_this_run(
          ['builder-cq', 'another-builder-cq']),
      api.post_process(DropExpectation),
  )
