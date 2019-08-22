# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'git_cl',
]


def RunSteps(api):
  api.git_cl.get_description(patch_url='foo', codereview='gerrit')

def GenTests(api):
  yield api.test('basic')
