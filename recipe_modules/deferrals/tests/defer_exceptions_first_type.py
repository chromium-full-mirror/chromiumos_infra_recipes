# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Ensures that the first exception type is preferred when that's requested."""

from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'deferrals',
]


def RunSteps(api):
  with api.deferrals.raise_exceptions_at_end(prefer_first_type=True):
    api.deferrals.defer_exception(StepFailure('exception'))
    api.deferrals.defer_exception(InfraFailure('exception'))


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
