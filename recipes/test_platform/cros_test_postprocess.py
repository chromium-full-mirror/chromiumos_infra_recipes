# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.chromeos.test_platform.cros_test_postprocess import CrosTestPostprocessRequest, TestResult

DEPS = [
    'breakpad',
    'recipe_engine/properties',
]

PROPERTIES = CrosTestPostprocessRequest

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def RunSteps(api, properties):
  api.breakpad.symbolicate_dump(properties.image_archive_path,
                                properties.test_results)


def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(
             image_archive_path=
             'gs://chromeos-image-archive/test-board-release/R10-11.0.0',
             test_results=[{
                 'path': TEST_RESULT_PATH
             }]) +  #
         api.breakpad.find_dmp_files_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filenames=['./a/b/c.dmp', './a/b/d.dmp']) +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filename='./a/b/c.dmp') +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=TestResult(path=TEST_RESULT_PATH),
             filename='./a/b/d.dmp'))
