# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for prototyping Chrome OS builders."""

DEPS = [
    'repo',
]


def RunSteps(api):
  api.repo.init('https://chromium.googlesource.com/chromiumos/manifest')


def GenTests(api):
  yield api.test('basic')
