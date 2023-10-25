# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import text_format

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  # projectA will not match any files, but its MigrationConfig has
  # fallback_to_default set, so it uses fallback_default_source_test_plan.
  relevant_plans = api.cros_test_plan_v2.relevant_plans([
      GerritChange(
          host='chromium-review.googlesource.com',
          project='src/projectA',
          change=123,
          patchset=3,
      ),
      GerritChange(
          host='chromium-review.googlesource.com',
          project='src/projectB',
          change=456,
          patchset=7,
      ),
  ])

  api.assertions.assertListEqual(
      relevant_plans,
      [
          api.cros_test_plan_v2.test_api.fallback_default_source_test_plan(),
          api.cros_test_plan_v2.test_api.fp_source_test_plan(),
          # TODO(b/286278022): Remove after incremental rollout to prod is complete
          api.cros_test_plan_v2.test_api
          .legacy_default_vm_test_plan_betty_arc_r(),
      ],
  )


def GenTests(api):

  yield api.test(
      'fallback-to-default',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          fallback_to_default=True,
                      ),
                  ])
          }),
      api.step_data(
          'find relevant plans.src/projectA.list output files',
          api.file.listdir(['']),
      ),
      api.step_data(
          'find relevant plans.src/projectB.list output files',
          api.file.listdir(['relevant_plan_1.textpb']),
      ),
      api.step_data(
          'find relevant plans.src/projectB.read output [CLEANUP]/test_plan_tmp_2/relevant_plan_1.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  api.cros_test_plan_v2.fp_source_test_plan(),
              ),
          ),
      ),
      api.post_process(
          post_process.StepCommandContains,
          'find relevant plans.src/projectA.call test_plan',
          [
              '[START_DIR]/cipd/test_plan/test_plan',
              'relevant-plans',
              '-loglevel',
              'debug',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectA/+/123/3',
              '-out',
              '[CLEANUP]/test_plan_tmp_1',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'find relevant plans.src/projectB.call test_plan',
          [
              '[START_DIR]/cipd/test_plan/test_plan',
              'relevant-plans',
              '-loglevel',
              'debug',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectB/+/456/7',
              '-out',
              '[CLEANUP]/test_plan_tmp_2',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
