# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.chromeos.test_platform.cros_test_postprocess import CrosTestPostprocessRequest, TestResult
from PB.test_platform.common.task import TaskLogData

DEPS = [
    'breakpad',
    'cros_test_postprocess',
    'urls',
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'util',
]


PROPERTIES = CrosTestPostprocessRequest

TEST_RESULT_PATH = 'gs://chromeos-autotest-results/swarming-1234'


def _download_test_result_files(api, remote_test_results):
  # Check each gs path for .dmp files before we download the entire thing.
  results_with_dumps = []
  with api.step.nest('check for .dmp files') as pres:
    for test_result in remote_test_results:
      gs_path = test_result.log_data.gs_url
      if not gs_path:
        continue

      with api.step.nest('check {}'.format(gs_path)):
        # We could just ls **.dmp but gsutil throws a CommandException if
        # there are no matching files, which causes the depot_tools logic
        # around gsutil to erroneously retry.
        files = api.gsutil.list(
            gs_path + '/**',
            stdout=api.raw_io.output_text(),
            ok_ret=(0, 1),
        ).stdout.strip().splitlines()

        dmpfiles = [fname for fname in files if fname.endswith('.dmp')]
        if dmpfiles:
          results_with_dumps.append(test_result)

    if not results_with_dumps:
      pres.step_summary_text = '(no .dmp files found)'

  if not results_with_dumps:
    return []

  # Download non-empty test results
  downloaded_test_results = []
  with api.step.nest('download test results'):
    for test_result in results_with_dumps:
      gs_path = test_result.log_data.gs_url
      with api.step.nest('download {}'.format(gs_path)):
        test_result_local_path = api.path.mkdtemp(prefix='test_result')
        step = api.gsutil.download_url(gs_path, test_result_local_path, ['-r'],
                                       multithreaded=True)
        step.presentation.links[gs_path] = api.urls.get_gs_path_url(gs_path)

        downloaded_test_results.append(
            api.cros_test_postprocess.downloaded_test_result(
                gs_path, test_result_local_path))

  return downloaded_test_results


def RunSteps(api, properties):
  downloaded_test_results = _download_test_result_files(
      api,
      properties.test_results,
  )

  if downloaded_test_results:
    api.breakpad.symbolicate_dump(
        properties.debug_symbols_archive_url,
        downloaded_test_results,
    )


def GenTests(api):
  # Test of symbolicate dumps.
  tr = TestResult(log_data=TaskLogData(gs_url=TEST_RESULT_PATH))
  empty_tr = TestResult(log_data=TaskLogData())
  req = CrosTestPostprocessRequest(
      debug_symbols_archive_url='gs://chromeos-image-archive/foox-release/R10-11.0.0',
      test_results=[tr, empty_tr],
  )
  dl_step = ('download test results.'
             'download gs://chromeos-autotest-results/swarming-1234')

  def _mock_gs_dmp_files(test_result, filenames):
    return api.step_data(
        'check for .dmp files.check {}.gsutil list'.format(
            test_result.log_data.gs_url),
        stdout=api.raw_io.output_text('\n'.join(filenames)), retcode=0)

  yield api.test(
      'basic',
      api.properties(req),
      _mock_gs_dmp_files(tr, ['./a/b/c.dmp', './a/b/d.dmp']),
      api.breakpad.find_dmp_files_test_data(
          test_result=tr, filenames=[b'./a/b/c.dmp', b'./a/b/d.dmp']),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/c.dmp'),
      api.breakpad.minidump_stackwalk_test_data(test_result=tr,
                                                filename='./a/b/d.dmp'),
      # A download step should exist; contrast this with the never-offloaded
      # testcase below.
      api.post_check(lambda check, steps: check(dl_step in steps)),
  )

  yield api.test(
      'no-dumps',
      api.properties(req),
      _mock_gs_dmp_files(tr, []),
      # A download step should not exist
      api.post_check(lambda check, steps: check(dl_step not in steps)),
  )

  yield api.test(
      'no-symbols-bundle-found',
      api.properties(req),
      _mock_gs_dmp_files(tr, ['./a/b/c.dmp', './a/b/d.dmp']),
      api.breakpad.gsutil_download_test_data(retcode=1),
      # A download step should not exist
      api.post_check(lambda check, steps: check('extract symbols' not in steps)
                    ),
  )
