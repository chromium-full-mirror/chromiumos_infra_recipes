# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'cros_schedule',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.cros_schedule.get_last_branched_mstone()
  api.cros_schedule.get_last_branched_mstone_n()


def GenTests(api):
  # Seed recent time Friday, February 19, 2021 12:30:23 AM for test data.
  yield api.test('basic', api.time.seed(1613694623.0))
