# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_sdk',
]


def RunSteps(api):
  api.cros_sdk(['--help'])
  api.cros_sdk.run(['ls'], env={'PATH': '/bin'})


def GenTests(api):
  yield api.test('basic')
