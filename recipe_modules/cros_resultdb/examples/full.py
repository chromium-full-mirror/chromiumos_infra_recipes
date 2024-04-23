# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import os
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



def RunSteps(api):
  rdb_config = api.json.loads(api.properties.get('rdb_config'))
  result_format = rdb_config.get('result_format')
  rdb_config['result_file'] = api.cros_resultdb.get_drone_result_file(
      '/base/dir', result_format) or ''
  rdb_config[
      'artifact_directory'] = api.cros_resultdb.get_drone_artifact_directory(
          '/base/dir', result_format) or ''
  api.cros_resultdb.upload(rdb_config, 'http://localhost/testhaus/url')
  if api.properties.get('result_adapter_cached'):
    # pylint: disable=protected-access
    api.cros_resultdb._ensure_result_adapter_executables()
  api.cros_resultdb.report_missing_test_cases(
      api.properties.get('missing_test_names'), base_variant={
          'some-key': 'some-value',
          'board': 'fake-board'
      })
  api.cros_resultdb.report_filtered_test_cases(
      api.properties.get('filtered_test_names'), base_variant={
          'some-key': 'some-value',
          'board': 'fake-board'
      }, reason='example reason')
  bigquery_export = invocation_pb2.BigQueryExport(
      project='cros-test-analytics', dataset='resultdb', table='test_results',
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
      api.properties(rdb_config=rdb_config_json,
                     missing_test_names=['missing-test']),
      api.post_process(post_process.StepFailure, 'upload test results to rdb'),
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

  yield api.test(
      'basic-tast-with-metadata',
      api.buildbucket.ci_build(
          tags=api.cros_tags.tags(**{
              'label-board': 'board',
              'build': 'board-cq/R11-123.45'
          })),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format':
                  'tast',
              'base_tags': [('test_suite', 'fake-suite')],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'board',
                  'build': 'board-cq/R11-123.45',
              },
              'test_metadata_file':
                  os.path.join('/base/dir', 'test_metadata.json'),
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-tast-with-invocation-artifacts-upload',
      api.buildbucket.ci_build(
          tags=api.cros_tags.tags(**{
              'label-board': 'board',
              'build': 'board-cq/R11-123.45'
          })),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'tast',
              'base_tags': [('test_suite', 'fake-suite')],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'board',
                  'build': 'board-cq/R11-123.45',
              },
              'invocation_artifacts_upload_to_rdb': True,
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-per-model-realm',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'use-current-realm',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-cq/R11-123.45',
              },
              'force_current_realm': True,
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'skip-board-model-check',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-cq/R11-123.45',
              },
              'force_current_realm': True,
              'skip_board_model_check': True
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
      api.post_process(
          post_process.DoesNotRun,
          'upload test results to rdb.fetch HEAD:generated/realms.cfg'),
  )

  yield api.test(
      'allowlisted-variant-per-model-realm',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-arc-r-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-arc-r-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'non-allowlisted-variant-per-model-realm',
      api.buildbucket.ci_build(),
      # The make-up board variant "brya-non-allowlisted-variant" is not included
      # in the variant allowlist.
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-non-allowlisted-variant-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-non-allowlisted-variant-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-shared-partner-vm-realm-for-base-vm-board',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'tast',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'betty'),
                  ('model', 'betty'),
                  ('image', 'betty-cq/R11-123.45'),
                  ('hostname', 'vm'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'betty',
                  'build': 'betty-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-shared-partner-vm-realm-for-vm-board-variant',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'tast',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'betty-arc-r'),
                  ('model', 'betty-arc-r'),
                  ('image', 'betty-arc-r-cq/R11-123.45'),
                  ('hostname', 'vm'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'betty-arc-r',
                  'build': 'betty-arc-r-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'non-allowlisted-basic-shared-partner-vm-realm',
      api.buildbucket.ci_build(),
      # The make-up vm board variant "non-allowlisted-variant" is not included
      # in the variant allowlist.
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'non-allowlisted-variant'),
                  ('model', 'taeko'),
                  ('image', 'non-allowlisted-variant-cq/R11-123.45'),
                  ('hostname', 'vm'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'non-allowlisted-variant',
                  'build': 'non-allowlisted-variant-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'basic-shared-partner-vm-realm-skipped-for-staging-vm-results',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'tast',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'betty'),
                  ('model', 'betty'),
                  ('image', 'staging-betty-cq/R11-123.45'),
                  ('hostname', 'vm'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'betty',
                  'build': 'staging-betty-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'mismatched-image-and-board',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'eve-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'eve-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'missing-per-model-realm',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'badmodel'),
                  ('image', 'brya-cq/R11-123.45'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-cq/R11-123.45',
              },
          })),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(post_process.MustRun,
                       'upload test results to rdb.run rdb'),
  )

  yield api.test(
      'multi-dut-per-model-realm',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=api.json.dumps({
              'result_format': 'gtest',
              'base_tags': [
                  ('test_suite', 'fake-suite'),
                  ('board', 'brya'),
                  ('model', 'taeko'),
                  ('image', 'brya-cq/R11-123.45'),
                  ('multiduts', 'True'),
                  ('secondary_boards', 'hatch'),
                  ('secondary_models', 'nipperkin'),
              ],
              'base_variant': {
                  'test_suite': 'fake-suite',
                  'board': 'brya',
                  'build': 'brya-cq/R11-123.45',
              },
          })),
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

  rdb_config['result_format'] = 'native'
  rdb_config_json = api.json.dumps(rdb_config)

  yield api.test(
      'basic-chromium_GPU_tests',
      api.buildbucket.ci_build(),
      api.properties(rdb_config=rdb_config_json),
      api.post_process(post_process.StepSuccess, 'upload test results to rdb'),
      api.post_process(
          post_process.StepCommandContains,
          'upload test results to rdb.run rdb', [
              '-result-file',
              '/base/dir/autoserv_test/chromium/results/native_results.jsonl',
              '-artifact-directory',
              '/base/dir/autoserv_test/',
              '-invocation-link-artifacts',
              'testhaus_logs=http://localhost/testhaus/url',
              '-trim-artifact-prefix',
              '/usr/local/autotest/results/lxc_job_folder',
          ]),
      api.post_process(post_process.DropExpectation),
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
      api.step_data('upload missing test cases (count: 2)',
                    api.raw_io.stream_output_text('{}'), retcode=1),
      api.post_process(post_process.MustRun,
                       'upload missing test cases (count: 2) (2)'),
  )

  yield api.test(
      'filtered-test-results',
      api.buildbucket.ci_build(),
      api.properties(
          rdb_config=rdb_config_json,
          filtered_test_names=['filtered-test', 'another-filtered-test']),
      api.step_data('upload filtered test cases (count: 2)',
                    api.raw_io.stream_output_text('{}'), retcode=1),
      api.post_process(post_process.MustRun,
                       'upload filtered test cases (count: 2) (2)'),
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
      api.post_process(post_process.StepFailure, 'upload test results to rdb'))
