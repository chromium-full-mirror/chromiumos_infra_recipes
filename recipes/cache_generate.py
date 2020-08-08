# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS cache payloads."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_cache',
    'git',
    'repo',
    'src_state',
]

CHROMIUMOS_CACHE_DIR = 'chromiumos_cache'


def RunSteps(api):
  with api.step.nest('repo checkout'):
    cache_dir = api.cros_cache.create_cache_dir(CHROMIUMOS_CACHE_DIR)
    with api.context(cwd=cache_dir):
      api.git.clone(api.src_state.internal_manifest.url, cache_dir)
      api.repo.init(manifest_url=api.src_state.internal_manifest.url)
      api.repo.sync(jobs=32)

  with api.context(cwd=cache_dir):
    with api.step.nest('package source'):
      cache_version = 'chromiumos_repo-{}.tar.gz'.format(
          api.time.ms_since_epoch())
      cache_file, version_file = api.cros_cache.package_source(
          cache_version, source_path=cache_dir)
    with api.step.nest('upload cache'):
      api.cros_cache.upload_artifact('chromeos-bot-cache', cache_file)

    with api.step.nest('update version'):
      api.cros_cache.upload_artifact('chromeos-bot-cache', version_file)


def GenTests(api):
  yield api.test('basic')
