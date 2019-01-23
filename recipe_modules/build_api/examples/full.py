# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'build_api',
]


def RunSteps(api):
  api.build_api.call_json('chromite.api.Service/Method', {})


def GenTests(api):
  yield api.test('basic')
