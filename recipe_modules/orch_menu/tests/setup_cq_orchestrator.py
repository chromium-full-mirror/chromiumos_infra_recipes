# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the setup_cq_orchestrator function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'gerrit',
    'orch_menu',
    'test_util',
]


def RunSteps(api):
  with api.orch_menu.setup_cq_orchestrator():
    pass


def GenTests(api):

  yield api.orch_menu.test(
      'basic',
      api.post_check(post_process.MustRun,
                     'set up orchestrator.configure builder'),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.sync manifest branches'),
      api.post_check(post_process.MustRun, 'check for merge conflicts'),
      cq=True,
      builder='cq-orchestrator',
  )

  yield api.orch_menu.test(
      'full-sync-experiment',
      api.buildbucket.try_build(
          builder='staging-cq-orchestrator',
          experiments=['chromeos.cq_orchestrator.full_sync']),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.configure builder'),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.sync cached directory'),
      api.post_check(post_process.MustRun, 'check for merge conflicts'),
      cq=True,
      builder='staging-cq-orchestrator',
  )

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False),
      api.post_process(post_process.DropExpectation),
      cq=True,
      with_history=True,
      status='FAILURE',
  )
