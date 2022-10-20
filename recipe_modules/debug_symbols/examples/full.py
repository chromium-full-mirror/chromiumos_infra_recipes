# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'debug_symbols',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.debug_symbols.upload_debug_symbols()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/debug_symbols': {
                  "cipd_ref": 'staging',
                  "gs_path": 'gs-test',
                  "worker_count": 90,
                  "retry_quota": 90,
                  "staging": True,
                  "dryrun": False,
              }
          }), api.post_check(post_process.StatusSuccess))
  yield api.test('needs-gs-path', api.post_check(post_process.StatusFailure))
