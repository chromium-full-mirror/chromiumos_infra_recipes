# -*- coding: utf-8 -*-

# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'metadata',
]


def RunSteps(api):
  _ = api


def GenTests(api):
  yield api.test('basic')
