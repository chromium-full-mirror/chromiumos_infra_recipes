# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/cq',
    'recipe_engine/file',
    'cros_version',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine.recipe_api import StepFailure


def RunSteps(api):

  with api.assertions.assertRaises(ValueError):
    _ = api.cros_version.read_workspace_version()

  with api.assertions.assertRaises(StepFailure):
    api.cros_version.bump_version(dry_run=False)


def GenTests(api):
  yield api.test(
      'empty-file',
      api.step_data('read chromeos version.read chromeos_version.sh',
                    api.file.read_text('')), api.cq(run_mode=api.cq.DRY_RUN))
