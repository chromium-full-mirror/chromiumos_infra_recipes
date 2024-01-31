# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'debug_symbols',
]



def RunSteps(api):
  api.debug_symbols.upload_debug_symbols()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/debug_symbols': {
                  'cipd_ref': 'staging',
                  'gs_path': 'gs-test',
                  'worker_count': 90,
                  'retry_quota': 90,
                  'staging': True,
                  'dryrun': False,
              }
          }))
  yield api.test(
      'prod',
      api.properties(
          **{
              '$chromeos/debug_symbols': {
                  'cipd_ref': 'prod',
                  'gs_path': 'gs-test',
                  'worker_count': 90,
                  'retry_quota': 90,
                  'staging': False,
                  'dryrun': False,
              }
          }))
  yield api.test(
      'needs-gs-path',
      status='FAILURE',
  )
