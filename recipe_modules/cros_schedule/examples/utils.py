# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'cros_schedule',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_schedule.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.cros_schedule.get_last_branched_mstone()
  api.cros_schedule.get_last_branched_mstone_n()


def GenTests(api):
  # Seed recent time Friday, February 19, 2021 12:30:23 AM for test data.
  yield api.test('basic', api.time.seed(1613694623.0))
