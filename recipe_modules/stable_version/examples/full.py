# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'stable_version',
]


def RunSteps(api):
  resp = api.stable_version.fetch_and_commit()
  api.assertions.assertEqual(resp, 'http://CL/123')

def GenTests(api):
  yield api.test('basic')