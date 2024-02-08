# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfigs

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'failures',
    'snapshot_orch_menu',
]


def RunSteps(api):
  if api.properties.get('fatal_failure'):
    fatal_failure = api.failures.Failure(kind='build', id='fake-build',
                                         title='fake-build', link_map={},
                                         fatal=True)
    api.snapshot_orch_menu.builds_status.update(failures=[fatal_failure])
  api.snapshot_orch_menu.run_follow_on_orchestrator()


def GenTests(api):

  yield api.snapshot_orch_menu.test(
      'basic',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.post_check(post_process.MustRun, 'run follow on orchestrator'),
      api.post_check(post_process.MustRun,
                     'run follow on orchestrator.collect.wait'),
      api.post_process(post_process.DropExpectation),
  )

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'artifact-generate-orchestrator'
  orch.orchestrator.follow_on_orchestrator.name = 'artifact-verify-orchestrator'
  orch.orchestrator.follow_on_orchestrator.await_completion = False
  yield api.snapshot_orch_menu.test(
      'does-not-await-completion',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.post_check(post_process.MustRun, 'run follow on orchestrator'),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.post_check(post_process.DoesNotRun,
                     'run follow on orchestrator.collect'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.snapshot_orch_menu.test(
      'follow-on-orch-timesout',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.step_data('run follow on orchestrator.collect.wait', retcode=1),
      api.post_check(post_process.MustRun, 'run follow on orchestrator'),
      api.post_check(post_process.MustRun, 'run follow on orchestrator.get'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.snapshot_orch_menu.test(
      'fatal-failures-no-follow-on-scheduled',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.properties(fatal_failure=True),
      api.post_check(post_process.DoesNotRun, 'run follow on orchestrator'),
      api.post_process(post_process.DropExpectation),
  )
