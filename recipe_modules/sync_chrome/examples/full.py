# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/path', 'sync_chrome']


def RunSteps(api):
  api.sync_chrome.sync_chrome(chrome_root=api.path['cache'].join('chrome'))


def GenTests(api):
  yield api.test('basic')
