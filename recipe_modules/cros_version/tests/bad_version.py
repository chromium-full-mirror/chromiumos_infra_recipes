# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/cq',
    'recipe_engine/file',
    'cros_version',
]

from recipe_engine.recipe_api import StepFailure


def RunSteps(api):

  with api.assertions.assertRaises(ValueError):
    _ = api.cros_version.read_workspace_version()

  with api.assertions.assertRaises(StepFailure):
    api.cros_version.bump_version(dry_run=False)


def GenTests(api):
  yield api.test(
      'empty_file',
      api.step_data('read chromeos version.read chromeos_version.sh',
                    api.file.read_raw('')), api.cq(run_mode=api.cq.DRY_RUN))
