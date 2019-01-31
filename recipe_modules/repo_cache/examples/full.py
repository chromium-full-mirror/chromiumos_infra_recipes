# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'repo_cache',
]


def RunSteps(api):
  api.repo_cache.ensure_fresh_cache(api.path['start_dir'],
                                    "https://example.com/manifest",
                                    init_opts=dict(manifest_branch='branchy'),
                                    sync_opts=dict(current_branch=False))


def GenTests(api):
  yield api.test('basic')
