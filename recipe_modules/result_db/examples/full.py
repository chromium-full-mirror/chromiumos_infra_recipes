# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'result_db',
]


def RunSteps(api):
  api.result_db.upload('skylab_test_runner', api.properties.get('test_args'))
  if 'result_adapter_cached' in api.properties:
    api.result_db.upload('skylab_test_runner', api.properties.get('test_args'))


def GenTests(api):

  rdb_settings = api.json.dumps({
      'result_format': 'gtest',
      'artifact_directory': '/tmp/artifact',
      'result_file': '[START_DIR]/chromium/output.json',
      'base_tags': ['test_suite:cast_shell_browsertests'],
      'base_variant': {
          'test_suite': 'cast_shell_browsertests',
      },
  })

  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
      api.path.exists(api.path['start_dir'].join('chromium', 'output.json')),
      api.properties(test_args='resultdb_settings=%s' %
                     base64.b64encode(rdb_settings)),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test result to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test result to rdb.run rdb'),
  )

  yield api.test(
      'cache result_adapter',
      api.buildbucket.ci_build(),
      api.properties(
          result_adapter_cached=True,
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_settings)),
      api.path.exists(api.path['start_dir'].join('chromium', 'output.json')),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test result to rdb'),
      api.post_process(
          post_process.DoesNotRun,
          'upload chromium test result to rdb (2).ensure result_adapter'),
      api.post_process(post_process.MustRun,
                       'upload chromium test result to rdb.run rdb'),
  )

  yield api.test(
      'non-exist result file',
      api.buildbucket.ci_build(),
      api.properties(test_args='resultdb_settings=%s' %
                     base64.b64encode(rdb_settings)),
      api.post_process(post_process.StepFailure,
                       'upload chromium test result to rdb'),
      api.post_process(
          post_process.StepTextContains, 'upload chromium test result to rdb',
          ['Result file [START_DIR]/chromium/output.json does not exist.']),
  )
