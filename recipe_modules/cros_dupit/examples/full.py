# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

DEPS = [
    'cros_dupit',
]


def RunSteps(api):
  api.cros_dupit.configure(dryrun=False)
  api.cros_dupit.run()
  assert api.cros_dupit.dryrun == False


def GenTests(api):
  yield api.test('basic')
