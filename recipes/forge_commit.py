# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for forcing forge commit failure.


Recipe used to force a forge commit failure so the failure response
can be analyzed to determine what user is being used for the invocation.
See https://crbug.com/1068743.
"""

DEPS = [
]


def RunSteps(api):
  pass


def GenTests(api):
  yield api.test('basic')
