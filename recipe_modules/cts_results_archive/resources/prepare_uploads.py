#!/usr/bin/python2
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This file is a bit of a mess, and we had to revert the linting because of an
# issue (b/197268039). So we're going to leave it alone until it can get a
# critical look. Thus, lots of pylint disables.
#
# pylint: disable=anomalous-backslash-in-string
# pylint: disable=redefined-builtin
# pylint: disable=undefined-variable
# pylint: disable=unused-import

import argparse
import glob
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
# For python2/python3-compatibility
try:
  from urllib import unquote
except ImportError:
  from urllib.parse import unquote

D = '[0-9][0-9]'
TIMESTAMP_PATTERN = '%s%s.%s.%s_%s.%s.%s' % (D, D, D, D, D, D, D)
CTS_RESULT_PATTERN = 'testResult.xml'
CTS_COMPRESSED_RESULT_PATTERN = 'testResult.xml.tgz'
CTS_V2_RESULT_PATTERN = 'test_result.xml'
CTS_V2_COMPRESSED_RESULT_PATTERN = 'test_result.xml.tgz'

CTS_COMPRESSED_RESULT_TYPES = {
    CTS_COMPRESSED_RESULT_PATTERN: CTS_RESULT_PATTERN,
    CTS_V2_COMPRESSED_RESULT_PATTERN: CTS_V2_RESULT_PATTERN,
}

# Autotest test to collect list of CTS tests
TEST_LIST_COLLECTOR = 'tradefed-run-collect-tests-only'


def main():
  """
  This script houses logic for archiving certain files extracted from hardware
  test logs to CTS specific Google Storage buckets.

  The script does not actually upload artifacts to Google Storage.
  - It prepares artifacts in the local directory provided.
  - It returns instructions for uploading artifacts in the response.

  This business logic is forklifted from gs_offloader:
  https://chromium.googlesource.com/chromiumos/third_party/autotest/+/2bb86dacf16b5ef589dc137e73e96bc4d17fed7a/site_utils/gs_offloader.py#399
  """
  logging.basicConfig(level=logging.DEBUG)

  ap = argparse.ArgumentParser()
  ap.add_argument('--json-input', type=argparse.FileType('r'))
  ap.add_argument('--json-output', type=argparse.FileType('w'))
  opts = ap.parse_args()

  # Input format
  data = json.load(opts.json_input)
  for key in ('dir', 'cts_results_gsurl', 'cts_apfe_gsurl', 'build', 'model',
              'parent_job_id'):
    if not data.get(key):
      raise ValueError('missing/invalid input field: ' + key)

  instructions = _prepare_uploads(data)

  # Output format
  json.dump(
      {
          # Each instruction is a dict:
          # {
          #   'name': str,
          #   'source': str (local directory path),
          #   'destination': str (Google Storage URL),
          # }
          'instructions': instructions,
      },
      opts.json_output,
  )
  return 0


def _prepare_uploads(data):
  """Prepare artifacts for CTS uploads.

    Upload testResult.xml.gz/test_result.xml.gz file to cts_results_bucket.
    Upload timestamp.zip to cts_apfe_bucket.

    @param args: Parsed command line arguments.
    @return: Instructions for uploading artifacts. See main for type
        information.
    """
  instructions = []
  for test_dir in glob.glob(os.path.join(data['dir'], '*')):
    cts_path = os.path.join(test_dir, 'cheets_CTS.*', 'results', '*',
                            TIMESTAMP_PATTERN)
    cts_v2_path = os.path.join(test_dir, 'cheets_CTS_*', 'results', '*',
                               TIMESTAMP_PATTERN)
    gts_v2_path = os.path.join(test_dir, 'cheets_GTS*', 'results', '*',
                               TIMESTAMP_PATTERN)
    sts_v2_path = os.path.join(test_dir, 'cheets_STS_*', 'results', '*',
                               TIMESTAMP_PATTERN)
    for result_path, result_pattern in [
        (cts_path, CTS_RESULT_PATTERN),
        (cts_path, CTS_COMPRESSED_RESULT_PATTERN),
        (cts_v2_path, CTS_V2_RESULT_PATTERN),
        (cts_v2_path, CTS_V2_COMPRESSED_RESULT_PATTERN),
        (gts_v2_path, CTS_V2_RESULT_PATTERN),
        (sts_v2_path, CTS_V2_RESULT_PATTERN)
    ]:
      for path in glob.glob(result_path):
        instructions += _prepare_uploads_for_test(path, result_pattern, data)
  return instructions


def _prepare_uploads_for_test(path, result_pattern, data):
  instructions = []
  apfe_gs_bucket = data['cts_apfe_gsurl']
  result_gs_bucket = data['cts_results_gsurl']
  build = data['build']
  host_model_name = data['model']
  parent_job_id = data['parent_job_id']

  if not _should_upload(build):
    # No need to upload current folder, return.
    return []

  job_id, package, timestamp = _parse_cts_job_results_file_path(path)

  # Results produced by CTS test list collector are dummy results.
  # They don't need to be copied to APFE bucket which is mainly being used for
  # CTS APFE submission.
  if not _is_test_collector(package):
    # Path: bucket/build/parent_job_id/cheets_CTS.*/job_id_timestamp/
    # or bucket/build/parent_job_id/cheets_GTS.*/job_id_timestamp/

    # build  = veyron_minnie-kernelnext-release/R90-12345.0.0
    builder = build.split('/')[0]
    if not builder.endswith('-release'):
      raise ValueError(
          'Non-release builds should already have been excluded, got %s' %
          build)

    # CTS v2 pipeline requires device info in 'board.model' format.
    # e.g. coral.robo-release, eve.eve-release, hatch.kohaku-kernelnext-release
    board_name, board_variant, build_version = re.search(
        "(\w+)(.*)/(.*)", build).groups()

    build_name_divo_format = (
        board_name + '.' + host_model_name + board_variant + '/' +
        build_version)

    cts_apfe_gs_suffix = os.path.join(build_name_divo_format, parent_job_id,
                                      package, job_id + '_' + timestamp)
    cts_apfe_gs_path = os.path.join(apfe_gs_bucket, cts_apfe_gs_suffix) + '/'

    for zip_file in glob.glob(os.path.join('%s.zip' % path)):
      instructions.append({
          'name': 'apfe:' + cts_apfe_gs_suffix,
          'source': zip_file,
          'destination': cts_apfe_gs_path,
      })
  else:
    logging.debug('%s is a CTS Test collector Autotest test run.', package)
    logging.debug('Skipping CTS results upload to APFE gs:// bucket.')

  # Path: bucket/cheets_CTS.*/job_id_timestamp/
  # or bucket/cheets_GTS.*/job_id_timestamp/
  test_result_gs_suffix = os.path.join(package, job_id + '_' + timestamp)
  test_result_gs_path = os.path.join(result_gs_bucket,
                                     test_result_gs_suffix) + '/'

  for test_result_file in glob.glob(os.path.join(path, result_pattern)):
    # gzip test_result_file(testResult.xml/test_result.xml)

    if test_result_file.endswith('tgz'):
      # Extract .xml file from tgz file for better handling in the
      # CTS dashboard pipeline.
      # TODO(rohitbm): work with infra team to produce .gz file so
      # tgz to gz middle conversion is not needed.
      try:
        with tarfile.open(test_result_file, 'r:gz') as tar_file:
          tar_file.extract(CTS_COMPRESSED_RESULT_TYPES[result_pattern],
                           path=path)
          test_result_file = os.path.join(
              path, CTS_COMPRESSED_RESULT_TYPES[result_pattern])
      except tarfile.ReadError as error:
        logging.debug(error)
      except KeyError as error:
        logging.debug(error)

    test_result_file_gz = '%s.gz' % test_result_file
    with open(test_result_file,
              'rb') as f_in, (gzip.open(test_result_file_gz, 'wb')) as f_out:
      shutil.copyfileobj(f_in, f_out)
    instructions.append({
        'name': 'results:' + test_result_gs_suffix,
        'source': test_result_file_gz,
        'destination': test_result_gs_path,
    })

  return instructions


def _should_upload(build):
  """Check if the result should be uploaded to CTS/GTS buckets.

    @param build: Builder name.

    @returns: Bool flag indicating whether a valid result.
    """
  # Not valid if it's not a release build.
  if not re.match(r'(?!trybot-).*-release/.*', build):
    return False

  return True


def _is_test_collector(package):
  """Returns true if the test run is just to collect list of CTS tests.

    @param package: Autotest package name. e.g. cheets_CTS_N.CtsGraphicsTestCase

    @return Bool flag indicating a test package is CTS list generator or not.
    """
  return TEST_LIST_COLLECTOR in package


def _parse_cts_job_results_file_path(path):
  """Parse CTS file paths an extract required information from them."""

  # Autotest paths look like:
  # /317739475-chromeos-test/chromeos4-row9-rack11-host22/
  # cheets_CTS.android.dpi/results/cts-results/2016.04.28_01.41.44

  # Swarming paths look like:
  # /swarming-458e3a3a7fc6f210/1/autoserv_test/
  # cheets_CTS.android.dpi/results/cts-results/2016.04.28_01.41.44

  folders = path.split(os.sep)
  if 'swarming' in folders[1]:
    # Swarming job and attempt combined
    job_id = "%s-%s" % (folders[-7], folders[-6])
  else:
    job_id = folders[-6]

  cts_package = folders[-4]
  timestamp = folders[-1]

  return job_id, cts_package, timestamp


if __name__ == '__main__':
  sys.exit(main())
