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
    'cros_source',
    'repo',
]


def RunSteps(api):
  with api.step.nest('repo checkout'):
    api.repo.init(manifest_url=api.cros_source.INTERNAL_MANIFEST_URL)
    api.repo.sync(jobs=32)

  with api.cros_source.checkout_overlays_context(), \
      api.context(cwd=api.cros_source.workspace_path):
    with api.step.nest('package source'):
      cache_version = 'chromiumos_repo-{}.bz2'.format(api.time.ms_since_epoch())
      cache_file, version_file = api.cros_cache.package_source(
          cache_version, source_path=api.cros_source.workspace_path)
    with api.step.nest('upload cache'):
      api.cros_cache.upload_artifact('chromeos-bot-cache', cache_file)

    with api.step.nest('update version'):
      api.cros_cache.upload_artifact('chromeos-bot-cache', version_file)


def GenTests(api):
  yield api.test('basic')
