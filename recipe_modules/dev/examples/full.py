# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

DEPS = [
    'dev',
]


def RunSteps(api):
  api.dev.configure(dryrun=False)
  assert api.dev.dryrun == False

def GenTests(api):
  yield api.test('basic')
