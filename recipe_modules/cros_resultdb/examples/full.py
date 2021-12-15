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
  rdb_config = api.json.loads(api.properties.get('rdb_config'))
  api.cros_resultdb.upload(rdb_config,
                           'gs://chromeos-test-logs/common-env/UUID/logs')


def GenTests(api):

  rdb_config = {
      'result_format': 'tast',
      'base_tags': ['test_suite:fake-suite'],
      'base_variant': {
          'test_suite': 'fake-suite',
          'board': 'board',
          'build': 'board-cq/R11-123.45',
      },
      'result_file': '/path/to/results',
      'artifact_directory': '/path/to/results',
  }
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'not-enabled',
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.post_process(post_process.StepWarning,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.DoesNotRun,
                       'upload chromium test results to rdb.run rdb'),
      api.post_process(post_process.StepWarning, 'upload test results to rdb'),
      api.post_process(post_process.DoesNotRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic_tast',
      api.buildbucket.ci_build(
          tags=api.cros_tags.tags(**{
              'label-board': 'board',
              'build': 'board-cq/R11-123.45'
          })),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'gtest'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'basic-gtest',
      api.buildbucket.ci_build(),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'skylab-test-runner'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'basic-skylab-test-runner',
      api.buildbucket.ci_build(),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  yield api.test(
      'rdb_failure',
      api.buildbucket.ci_build(),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.step_data('upload chromium test results to rdb.run rdb', retcode=1),
  )

  yield api.test(
      'cache result_adapter',
      api.buildbucket.ci_build(),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.properties(
          result_adapter_cached=True,
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json)),
      api.post_process(post_process.StepSuccess,
                       'upload chromium test results to rdb'),
      api.post_process(
          post_process.DoesNotRun,
          'upload chromium test results to rdb (2).ensure result_adapter'),
      api.post_process(post_process.MustRun,
                       'upload chromium test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'not-supported'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'not-supported-format', api.buildbucket.ci_build(),
      api.properties(
          test_args='resultdb_settings=%s' % base64.b64encode(rdb_config_json),
          rdb_config=rdb_config_json),
      api.post_process(post_process.StepWarning,
                       'upload chromium test results to rdb'))
