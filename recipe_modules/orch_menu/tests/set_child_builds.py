# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'orch_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    api.orch_menu.plan_and_run_children()

    # Run tests so that the test runner doesn't get grumpy about unused mock
    # step data from orch_menu.standard_test_data().
    api.orch_menu.plan_and_run_tests()


def GenTests(api):

  def schedule_build_step(builder_name):
    return '.'.join(['run builds', 'schedule new builds', builder_name])

  yield api.orch_menu.test(
      'child-builds',
      api.orch_menu.standard_test_data().ctp_normal,
      api.properties(**{
          '$chromeos/orch_menu': {
              'child_builds': ['amd64-generic-postsubmit',],
          }
      }),
      api.post_check(post_process.MustRun,
                     schedule_build_step('amd64-generic-postsubmit')),
      api.post_check(post_process.DoesNotRun,
                     schedule_build_step('arm-generic-postsubmit')),
      api.post_check(post_process.DoesNotRun,
                     schedule_build_step('grunt-postsubmit')),
      api.post_process(post_process.DropExpectation),
  )
