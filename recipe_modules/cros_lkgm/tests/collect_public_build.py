# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'cros_lkgm',
]



def RunSteps(api):
  # Called collect_public_build without first calling schedule_public_build.
  api.cros_lkgm.collect_public_build()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StepFailure, 'collect public orchestrator'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='FAILURE')
