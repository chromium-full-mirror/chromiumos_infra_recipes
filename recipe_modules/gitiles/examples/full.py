# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gitiles',
]


def RunSteps(api):
  api.gitiles.fetch_revision('testgerrit', 'my/project', 'master')


def GenTests(api):
  yield api.test('basic')
