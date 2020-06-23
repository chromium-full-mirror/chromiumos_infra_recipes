# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'tast_exec',
]


def RunSteps(api):
  fake_file = api.path.mkstemp(prefix='temp')
  fake_dir = api.path.mkdtemp(prefix='temp')
  api.tast_exec.run('tast_vm', '!informational', fake_file, fake_dir, fake_file)


def GenTests(api):
  yield api.test('basic')
