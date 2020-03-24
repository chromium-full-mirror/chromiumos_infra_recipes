# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

from recipe_engine.util import exponential_retry

from PB.recipes.chromeos.test_platform.cros_test_postprocess import CrosTestPostprocessRequest, TestResult
from PB.test_platform.common.task import TaskLogData

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
      gs_path = test_result.log_data.gs_url
      _wait(api, gs_path)
      with api.step.nest('download {}'.format(gs_path)):
        test_result_local_path = api.path.mkdtemp(prefix='test_result')
        step = api.gsutil.download_url(gs_path,
                                       test_result_local_path, ['-r'],
                                       multithreaded=True)
        step.presentation.links[gs_path] = api.urls.get_gs_path_url(gs_path)

        downloaded_test_results.append(
            api.cros_test_postprocess.downloaded_test_result(
                gs_path, test_result_local_path))

  return downloaded_test_results

def _wait(api, gs_path):
  with api.step.nest('wait'):
    try:
      # Note: This noop step is provided only to allow a test of the failure
      # pathway that sidesteps the exponential backoff and sleep of
      # _wait_for_marker_file.
      api.step('noop', ['cat', '/dev/null'])
      with api.step.nest('poll gs'):
        _wait_for_marker_file(api, gs_path)
    except:
        raise api.step.StepFailure(
            'timed out or failed waiting offload-finished marker to appear')

# With these parameters, polling will wait for (2 + 4 + 8) = 14 minutes before
# giving up.
@exponential_retry(retries=4, delay=datetime.timedelta(minutes=2))
def _wait_for_marker_file(api, gs_path):
  """Poll gs until the offload-finished marker appears for it."""
  completed_marker = api.path.join(gs_path, '.finished_offload')
  api.gsutil.cat(completed_marker)


def RunSteps(api, properties):
  downloaded_test_results = _download_test_result_files(
      api, properties.test_results)

  api.breakpad.symbolicate_dump(properties.debug_symbols_archive_url,
                                downloaded_test_results)

  # TODO (guocb): add more postprocessing, e.g. gen provision events, etc.


def GenTests(api):
  # Test of symbolicate dumps.
  tr = TestResult(log_data=TaskLogData(gs_url=TEST_RESULT_PATH))
  req = CrosTestPostprocessRequest(
      debug_symbols_archive_url=
          'gs://chromeos-image-archive/foox-release/R10-11.0.0',
      test_results=[tr],
  )
  dl_step = ('download test results.'
             'download gs://chromeos-autotest-results/swarming-1234')
  yield (api.test('basic') +  #
         api.properties(req) +  #
         api.breakpad.find_dmp_files_test_data(
             test_result=tr,
             filenames=['./a/b/c.dmp', './a/b/d.dmp']) +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=tr,
             filename='./a/b/c.dmp') +  #
         api.breakpad.minidump_stackwalk_test_data(
             test_result=tr,
             filename='./a/b/d.dmp') + #
         # A download step should exist; contrast this with the never-offloaded
         # testcase below.
         api.post_check(lambda check, steps: check(dl_step in steps)))

  yield (api.test('never-offloaded') + #
         api.properties(req) + #
         api.step_data('download test results.wait.noop', retcode=1) + #
         # Failure when waiting for offload means we should not attempt
         # download.
         api.post_check(lambda check, steps: check(dl_step not in steps)))
