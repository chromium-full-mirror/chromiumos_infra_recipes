# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'breakpad',
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
]

from PB.recipes.chromeos.test_platform.cros_test_postprocess import TestResult

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def RunSteps(api):
  stackwalk_output_paths = api.breakpad.symbolicate_dump(
      image_archive_path=
      'gs://chromeos-image-archive/test-board-release/R10-11.0.0',
      test_results=[
          TestResult(path=TEST_RESULT_PATH),
      ])

  api.assertions.assertEqual(len(stackwalk_output_paths), 2)
  api.assertions.assertEqual(stackwalk_output_paths[0].pieces[-1],
                             'a/b/c.dmp.txt')
  api.assertions.assertEqual(stackwalk_output_paths[1].pieces[-1],
                             'a/b/d.dmp.txt')


def GenTests(api):
  yield (api.test('basic') +  #
         api.breakpad.find_dmp_files_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filenames=['./a/b/c.dmp', './a/b/d.dmp']) +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filename='./a/b/c.dmp') +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filename='./a/b/d.dmp'))
