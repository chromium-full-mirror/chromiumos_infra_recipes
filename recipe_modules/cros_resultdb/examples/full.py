# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'cros_resultdb',
    'cros_tags',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  rdb_config = api.json.loads(api.properties.get('rdb_config'))
  result_format = rdb_config.get('result_format')
  rdb_config['result_file'] = api.cros_resultdb.get_drone_result_file(
      '/base/dir', result_format) or ''
  rdb_config[
      'artifact_directory'] = api.cros_resultdb.get_drone_artifact_directory(
          '/base/dir', result_format) or ''
  api.cros_resultdb.upload(rdb_config,
                           b'gs://chromeos-test-logs/common-env/UUID/logs')
  if api.properties.get('result_adapter_cached'):
    # pylint: disable=protected-access
    api.cros_resultdb._ensure_result_adapter_executables()
  api.cros_resultdb.report_missing_test_cases(
      api.properties.get('missing_test_names'), base_variant={
          'some-key': 'some-value',
          'board': 'fake-board'
      })
  bigquery_export = invocation_pb2.BigQueryExport(
      project="cros-test-analytics", dataset="resultdb", table="test_results",
      test_results=invocation_pb2.BigQueryExport.TestResults())
  api.cros_resultdb.export_invocation_to_bigquery([bigquery_export])


def GenTests(api):

  rdb_config = {
      'result_format': 'tast',
      'base_tags': [('test_suite', 'fake-suite')],
      'base_variant': {
          'test_suite': 'fake-suite',
          'board': 'board',
          'build': 'board-cq/R11-123.45',
      },
  }
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'not-enabled',
      api.properties(
          rdb_config=rdb_config_json, missing_test_names=['missing-test']),
      api.post_process(post_process.StepWarning, 'upload test results to rdb'),
      api.post_process(post_process.DoesNotRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-tast',
      api.buildbucket.ci_build(
          tags=api.cros_tags.tags(**{
              'label-board': 'board',
              'build': 'board-cq/R11-123.45'
          })),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'gtest'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'basic-gtest',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'skylab-test-runner'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'basic-skylab-test-runner',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'missing-test-results',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=rdb_config_json,
          missing_test_names=['missing-test', 'another-missing-test']),
      api.step_data('upload missing test cases',
                    api.raw_io.stream_output_text('{}'), retcode=1),
      api.post_process(post_process.MustRun, 'upload missing test cases (2)'),
  )

  yield api.test(
      'export-invocation-to-bigquery',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess,
                       'mark resultdb invocation for bigquery export'),
  )

  yield api.test(
      'rdb-failure',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.step_data('upload test results to rdb.run rdb', retcode=1),
  )

  yield api.test(
      'cache-result_adapter',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.properties(
          result_adapter_cached=True,
      ),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.DoesNotRun,
                       'upload test results to rdb (2).ensure result_adapter'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  rdb_config['result_format'] = 'not-supported'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'not-supported-format', api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepWarning, 'upload test results to rdb'))
