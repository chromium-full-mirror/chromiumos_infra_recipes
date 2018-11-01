# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for prototyping Chrome OS builders."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',

    'cros_sdk',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  repo_cache_path = api.repo_cache.ensure_fresh_cache(
      'chromiumos', MANIFEST_URL, init_opts=dict(groups=['path:chromite']))

  repo_work_path = api.path['start_dir'].join('chromiumos')
  api.file.ensure_directory('repo work dir', repo_work_path)
  with api.overlayfs.context('repo', repo_cache_path, repo_work_path):
    api.cros_sdk.run(['./update_chroot'])


def GenTests(api):
  yield api.test('basic')
