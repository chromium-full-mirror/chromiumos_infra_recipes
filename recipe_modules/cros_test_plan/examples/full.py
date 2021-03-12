# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_plan',
]


def RunSteps(api):
  test_plan = api.cros_test_plan.generate([Build()], [GerritChange()],
                                          GitilesCommit(id='1234abcd'))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='lts-cq-orchestrator'),
      api.post_check(post_process.StepCommandContains,
                     'generate test plan.ensure test_planner.ensure_installed',
                     ['chromiumos/infra/test_plan_generator/${platform} prod']),
  )

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-main-release-orchestrator',
      ),
      api.post_check(
          post_process.StepCommandContains,
          'generate test plan.ensure test_planner.ensure_installed',
          ['chromiumos/infra/test_plan_generator/${platform} staging']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{
              "$chromeos/cros_test_plan": {
                  "test_plan_generator_cipd_package": "test_plan_generator_foo",
                  "test_plan_generator_cipd_ref": "bar",
              }
          }),
      api.post_check(post_process.StepCommandContains,
                     'generate test plan.ensure test_planner.ensure_installed',
                     ['test_plan_generator_foo bar']),
  )
