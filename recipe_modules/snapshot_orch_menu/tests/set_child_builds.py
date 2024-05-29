# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'snapshot_orch_menu',
    'test_util',
]


def RunSteps(api):
  with api.snapshot_orch_menu.setup_orchestrator():
    api.snapshot_orch_menu.plan_and_run_children()


def GenTests(api):

  def schedule_build_step(builder_name):
    return '.'.join(['run builds', 'schedule new builds', builder_name])

  yield api.snapshot_orch_menu.test(
      'child-builds',
      api.properties(
          **{
              '$chromeos/snapshot_orch_menu': {
                  'child_builds': ['amd64-generic-snapshot',],
              }
          }),
      api.post_check(post_process.MustRun,
                     schedule_build_step('amd64-generic-snapshot')),
      api.post_check(post_process.DoesNotRun,
                     schedule_build_step('arm-generic-snapshot')),
      api.post_check(post_process.DoesNotRun,
                     schedule_build_step('grunt-snapshot')),
      api.post_process(post_process.DropExpectation),
  )
