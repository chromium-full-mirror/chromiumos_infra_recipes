# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from PB.recipes.chromeos.test_platform.cros_test_postprocess import CrosTestPostprocessRequest, TestResult

DEPS = [
    'breakpad',
    'cros_test_postprocess',
    'urls',
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = CrosTestPostprocessRequest

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def _download_test_result_files(api, remote_test_results):
  downloaded_test_results = []

  with api.step.nest('download test results'):
    for test_result in remote_test_results:
      with api.step.nest('download {}'.format(test_result.path)):
        gs_path = test_result.path
        test_result_local_path = api.path.mkdtemp(prefix='test_result')
        step = api.gsutil.download_url(test_result.path,
                                       test_result_local_path, ['-r'],
                                       multithreaded=True)
        step.presentation.links[gs_path] = api.urls.get_gs_path_url(gs_path)

        downloaded_test_results.append(
            api.cros_test_postprocess.downloaded_test_result(
                gs_path, test_result_local_path))

  return downloaded_test_results


def RunSteps(api, properties):
  downloaded_test_results = _download_test_result_files(
      api, properties.test_results)

  api.breakpad.symbolicate_dump(properties.image_archive_path,
                                downloaded_test_results)

  # TODO (guocb): add more postprocessing, e.g. gen provision events, etc.


def GenTests(api):
  # Test of symbolicate dumps.
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
