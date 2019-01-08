# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/file',
    'artifacts'
]

from recipe_engine import config_types

def RunSteps(api):
  sd = api.path['start_dir']

  api.file.ensure_directory('create artifact dir', sd.join('artifact_dir'))

  api.artifacts.upload(
      sd.join('artifact_dir'),
      api.properties['buildername'],
      api.properties['buildbucket_build_id'],
      api.properties['gs_buckets'])


def GenTests(api):
  yield (api.test('default_bucket') +
    api.properties(
      buildername='builder',
      buildbucket_build_id='123454321',
      gs_buckets=None
    )
  )

  yield (api.test('override_bucket') +
    api.properties(
      buildername='builder',
      buildbucket_build_id='123454321',
      gs_buckets=['artifact-bucket']
    )
  )

