# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_relevance',
    'orch_menu',
]


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    api.assertions.assertEqual(api.orch_menu.plan_and_wait_for_images(), [])


def GenTests(api):

  yield api.orch_menu.test(
      'no-necessary-builders',
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[], skipped_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
          ], step_name='run builds.plan builds.read output file'),
      api.post_process(post_process.DoesNotRun, 'run builds.collect'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
      cq=True,
  )
