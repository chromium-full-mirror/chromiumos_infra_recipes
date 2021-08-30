# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'breakpad',
    'cros_test_postprocess',
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def RunSteps(api):
  api.breakpad.symbolicate_dump(
      image_archive_path='gs://chromeos-image-archive/test-board-release/R10-11.0.0',
      test_results=[
          api.cros_test_postprocess.downloaded_test_result(
              gs_path=TEST_RESULT_PATH,
              local_path=api.path.mkdtemp('test_result'))
      ])


def GenTests(api):
  yield api.test(
      'no symbols bundle found',
      api.breakpad.gsutil_download_test_data(retcode=1),
      # A download step should not exist
      api.post_check(lambda check, steps: check('extract symbols' not in steps)
                    ),
  )
