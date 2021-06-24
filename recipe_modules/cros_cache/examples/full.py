# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_cache',
    'cros_source',
    'repo',
    'workspace_util',
]


def RunSteps(api):
  cache_dir = api.cros_cache.create_cache_dir('temp_cache')
  with api.workspace_util.setup_workspace(default_main=True), \
      api.context(cwd=cache_dir):
    api.cros_source.ensure_synced_cache()
    cache_file, version_file = api.cros_cache.package_source(
        'test_file.tar.gz', api.cros_source.workspace_path)
    api.cros_cache.upload_artifact('test cache upload', cache_file)
    api.cros_cache.upload_artifact('test cache version', version_file)


def attempt_upload_file(api, attempt):
  step_text = 'gsutil cp'
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text, times_out_after=(api.cros_cache.gsutil_timeout_seconds + 1))


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'missing-source-tree',
      api.step_data('tar up source repo checkout.write version file',
                    retcode=1),
  )

  yield api.test(
      'retry-success-gsutil',
      attempt_upload_file(api, 1),
      attempt_upload_file(api, 2),
  )

  yield api.test(
      'retry-fail-gsutil',
      attempt_upload_file(api, 1),
      attempt_upload_file(api, 2) + attempt_upload_file(api, 3),
  )
