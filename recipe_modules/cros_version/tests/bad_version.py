# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/file',
    'cros_version',
]



def RunSteps(api):

  with api.assertions.assertRaises(ValueError):
    _ = api.cros_version.read_workspace_version()

  with api.assertions.assertRaises(StepFailure):
    api.cros_version.bump_version(dry_run=False)


def GenTests(api):
  yield api.test(
      'empty-file', api.buildbucket.try_build(),
      api.step_data('read chromeos version.read chromeos_version.sh',
                    api.file.read_text('')), api.cv(run_mode=api.cv.DRY_RUN))
