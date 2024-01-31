# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure

DEPS = [
    'recipe_engine/step',
    'deferrals',
]



def RunSteps(api):
  # Set up deferrals to defer.
  with api.deferrals.raise_exceptions_at_end():
    # Swallow deferrals of the next step.
    with api.deferrals.defer_exceptions():
      api.step('a failed step', ['ls'])
    raise InfraFailure('failed')


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('a failed step', retcode=1),
      api.post_check(post_process.StepFailure, 'a failed step'),
      # Infra failure, not regular exception.
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
