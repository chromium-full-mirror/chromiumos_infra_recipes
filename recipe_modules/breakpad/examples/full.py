# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'breakpad',
    'cros_test_postprocess',
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]

from PB.recipes.chromeos.test_platform.cros_test_postprocess import TestResult
from PB.test_platform.common.task import TaskLogData

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def RunSteps(api):
  stackwalk_output_paths = api.breakpad.symbolicate_dump(
      image_archive_path='gs://chromeos-image-archive/test-board-release/R10-11.0.0',
      test_results=[
          api.cros_test_postprocess.downloaded_test_result(
              gs_path=TEST_RESULT_PATH,
              local_path=api.path.mkdtemp('test_result'))
      ])

  api.assertions.assertEqual(len(stackwalk_output_paths), 2)
  api.assertions.assertEqual(stackwalk_output_paths[0].pieces[-1],
                             'a/b/c.dmp.txt')
  api.assertions.assertEqual(stackwalk_output_paths[1].pieces[-1],
                             'a/b/d.dmp.txt')


def GenTests(api):
  tr = TestResult(log_data=TaskLogData(gs_url=TEST_RESULT_PATH))
  yield api.test(
      'basic',
      api.breakpad.find_dmp_files_test_data(
          test_result=tr,
          filenames=['./a/b/c.dmp', './a/b/d.dmp', './a/b/corrupted.dmp']),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/c.dmp'),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/d.dmp'),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/corrupted.dmp',
                                                retcode=1),
  )
