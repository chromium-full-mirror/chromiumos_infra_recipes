# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'cros_test_plan_v2',
]



def RunSteps(api):
  api.cros_test_plan_v2.dirmd_update('proj.dataset.mytable')


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandEquals,
          'dirmd update.call test_plan',
          [
              '[START_DIR]/cipd/test_plan/test_plan', 'chromeos-dirmd-update',
              '-crossrcroot', '[CLEANUP]/chromiumos_workspace', '-table',
              'proj.dataset.mytable', '-loglevel', 'debug'
          ],
      ),
  )
