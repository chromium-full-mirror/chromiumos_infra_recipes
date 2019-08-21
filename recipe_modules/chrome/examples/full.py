# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/path', 'chrome']


def RunSteps(api):
  api.chrome.sync(
      chrome_root=api.path['start_dir'].join('chrome'),
      internal=True,
  )
  api.chrome.sync(
      chrome_root=api.path['start_dir'].join('chrome'),
      internal=False,
  )


def GenTests(api):
  yield api.test('basic')
