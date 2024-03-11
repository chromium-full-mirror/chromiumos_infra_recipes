# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipes.chromeos.test_platform.cros_test_postprocess import TestResult
from PB.test_platform.common.task import TaskLogData

DEPS = [
    'breakpad',
    'cros_test_postprocess',
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]


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
  api.assertions.assertTrue(
      str(stackwalk_output_paths[0]).endswith('a/b/c.dmp.txt'))
  api.assertions.assertTrue(
      str(stackwalk_output_paths[1]).endswith('a/b/d.dmp.txt'))


def GenTests(api):
  tr = TestResult(log_data=TaskLogData(gs_url=TEST_RESULT_PATH))
  yield api.test(
      'basic',
      api.breakpad.find_dmp_files_test_data(
          test_result=tr,
          filenames=[b'./a/b/c.dmp', b'./a/b/d.dmp', b'./a/b/corrupted.dmp']),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/c.dmp'),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/d.dmp'),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/corrupted.dmp',
                                                retcode=1),
  )
