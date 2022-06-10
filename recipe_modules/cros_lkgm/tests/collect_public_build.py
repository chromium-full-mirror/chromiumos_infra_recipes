# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_lkgm',
]

from recipe_engine import post_process

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  # Called collect_public_build without first calling schedule_public_build.
  api.cros_lkgm.collect_public_build()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StepFailure, 'collect public orchestrator'),
      api.post_process(post_process.DropExpectation))
