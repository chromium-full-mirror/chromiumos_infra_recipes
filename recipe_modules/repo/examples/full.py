# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'repo',
]


def RunSteps(api):
  api.repo(['help'], name='help step')
  api.repo.init('http://manifest_url')
  api.repo.init('http://manifest_url', manifest_branch='mybranch',
                groups=['group1', 'group2'], depth=10,
                repo_url='http://repo_url')
  api.repo.sync()
  api.repo.sync(force_sync=True, detach=True, current_branch=True, jobs=99,
                no_tags=True, optimized_fetch=True, cache_dir='/tmp/cache')


def GenTests(api):
  yield api.test('setup_repo')
