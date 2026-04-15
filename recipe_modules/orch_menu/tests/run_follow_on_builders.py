# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring

from PB.chromiumos.builder_config import BuilderConfigs
from RECIPE_MODULES.chromeos.failures.api import Failure

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'orch_menu',
]


def RunSteps(api):
  if api.properties.get('fatal_failure'):
    fatal_failure = Failure(kind='build', id='fake-build', title='fake-build',
                            link_map={}, fatal=True)
    api.orch_menu.builds_status.update(failures=[fatal_failure])

  api.orch_menu.run_follow_on_builders()


def GenTests(api):
  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'artifact-generate-orchestrator'

  followers = orch.orchestrator.follow_on_builders
  followers.names.extend(
      ['chromeos/firmware/firmware-android-R148-16640.2.B-branch'])
  followers.await_completion = True
  followers.rev_bump = True

  yield api.orch_menu.test(
      'basic',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.post_check(
          post_process.MustRun,
          'run follow on builders.run follow on builder chromeos/firmware/firmware-android-R148-16640.2.B-branch'
      ),
      api.post_process(post_process.DropExpectation),
  )

  configs_no_bump = BuilderConfigs()
  orch_no_bump = configs_no_bump.builder_configs.add()
  orch_no_bump.id.name = 'artifact-generate-orchestrator'
  followers_no_bump = orch_no_bump.orchestrator.follow_on_builders
  followers_no_bump.names.extend(
      ['chromeos/firmware/firmware-android-R148-16640.2.B-branch'])
  followers_no_bump.await_completion = True
  followers_no_bump.rev_bump = False

  yield api.orch_menu.test(
      'no-rev-bump',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.cros_infra_config.override_builder_configs_test_data(configs_no_bump),
      api.post_check(
          post_process.MustRun,
          'run follow on builders.run follow on builder chromeos/firmware/firmware-android-R148-16640.2.B-branch'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.orch_menu.test(
      'fatal-failures-no-follow-on-scheduled',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.properties(fatal_failure=True),
      api.post_check(post_process.DoesNotRun, 'run follow on builders'),
      api.post_process(post_process.DropExpectation),
  )

  configs_empty = BuilderConfigs()
  orch_empty = configs_empty.builder_configs.add()
  orch_empty.id.name = 'artifact-generate-orchestrator'

  yield api.orch_menu.test(
      'empty-followers',
      api.buildbucket.ci_build(builder='artifact-generate-orchestrator'),
      api.cros_infra_config.override_builder_configs_test_data(configs_empty),
      api.post_process(post_process.DropExpectation),
  )
