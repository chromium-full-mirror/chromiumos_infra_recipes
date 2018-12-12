# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

DEPS = [
    'git',
]


def RunSteps(api):
  api.git.fetch('remote')
  assert api.git.fetch_ref('remote', 'refs/heads/branch') == 'deadbeef'
  api.git.checkout('master', force=True)
  api.git.cherry_pick('branch')
  api.git.commit_files(['README.md'], 'Updated README\n\nMuch better now.')
  api.git.push('origin', 'HEAD:master', capture_stdout=True)


def GenTests(api):
  yield api.test('basic')
