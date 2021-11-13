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
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'cros_resultdb',
    'cros_tags',
]


def RunSteps(api):
  api.cros_resultdb.upload_chromium_tests(
      api.properties.get('test_args'), 'dummy-results-dir')
  api.cros_resultdb.upload_chromeos_tests(
      'dummy-result-dir', 'gs://chromeos-test-logs/common-env/UUID/logs')
  if 'result_adapter_cached' in api.properties:
    api.cros_resultdb.upload_chromium_tests(
        api.properties.get('test_args'), 'dummy-results-dir')
    api.cros_resultdb.upload_chromeos_tests(
        'dummy-result-dir', 'gs://chromeos-test-logs/common-env/UUID/logs')


def GenTests(api):

  rdb_settings = api.json.dumps({
      'result_format': 'tast',
      'base_tags': ['test_suite:cast_shell_browsertests'],
      'base_variant': {
          'test_suite': 'lacros_all_tast_tests',
      },
  })

  yield api.test(
      'basic_tast',
      api.buildbucket.ci_build(
          tags=api.cros_tags.tags(**{
              'label-board': 'eve',
              'build': 'eve-cq/R11-123.45'
          })),
      api.properties(test_args='resultdb_settings=%s' %
                     base64.b64encode(rdb_settings)),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  rdb_settings = api.json.dumps({
      'result_format': 'gtest',
      'base_tags': ['test_suite:cast_shell_browsertests'],
      'base_variant': {
          'test_suite': 'lacros_all_tast_tests',
      },
      'artifact_directory': 'chromium/debug',
  })

  yield api.test(
      'basic_gtest',
      api.buildbucket.ci_build(),
      api.properties(test_args='resultdb_settings=%s' %
                     base64.b64encode(rdb_settings)),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  yield api.test(
      'rdb_failure',
      api.buildbucket.ci_build(),
      api.properties(test_args='resultdb_settings=%s' %
                     base64.b64encode(rdb_settings)),
      api.step_data('upload chromium test results to rdb.run rdb', retcode=1),
  )

  yield api.test(
      'cache result_adapter',
      api.buildbucket.ci_build(),
      api.properties(
          result_adapter_cached=True,
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_settings)),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(
          post_process.DoesNotRun,
          'upload chromium test results to rdb (2).ensure result_adapter'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )
