#!/usr/bin/python2
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
import urllib

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
  dir = data['dir']
  cts_results_gsurl = data['cts_results_gsurl']
  cts_apfe_gsurl = data['cts_apfe_gsurl']

  instructions = _prepare_uploads(dir, cts_results_gsurl, cts_apfe_gsurl)

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


def _prepare_uploads(dir, cts_results_gsurl, cts_apfe_gsurl):
  """Prepare artifacts for CTS uploads.

    Upload testResult.xml.gz/test_result.xml.gz file to cts_results_bucket.
    Upload timestamp.zip to cts_apfe_bucket.

    @param args: Parsed command line arguments.
    @return: Instructions for uploading artifacts. See main for type
        information.
    """
  instructions = []
  for test_dir in glob.glob(os.path.join(dir, '*')):
    cts_path = os.path.join(test_dir, 'cheets_CTS.*', 'results', '*',
                            TIMESTAMP_PATTERN)
    cts_v2_path = os.path.join(test_dir, 'cheets_CTS_*', 'results', '*',
                               TIMESTAMP_PATTERN)
    gts_v2_path = os.path.join(test_dir, 'cheets_GTS*', 'results', '*',
                               TIMESTAMP_PATTERN)
    for result_path, result_pattern in [
        (cts_path, CTS_RESULT_PATTERN),
        (cts_path, CTS_COMPRESSED_RESULT_PATTERN),
        (cts_v2_path, CTS_V2_RESULT_PATTERN),
        (cts_v2_path, CTS_V2_COMPRESSED_RESULT_PATTERN),
        (gts_v2_path, CTS_V2_RESULT_PATTERN)
    ]:
      for path in glob.glob(result_path):
        instructions += _prepare_uploads_for_test(test_dir, path,
                                                  result_pattern,
                                                  cts_results_gsurl,
                                                  cts_apfe_gsurl)
  return instructions



def _prepare_uploads_for_test(dir, path, result_pattern, result_gs_bucket,
                              apfe_gs_bucket):
  instructions = []
  keyval = _parse_job_keyval(dir)
  build = keyval.get('build')
  suite = keyval.get('suite')

  host_keyval = _parse_host_keyval(dir, keyval.get('hostname'))
  labels = urllib.unquote(host_keyval.get('labels'))
  try:
    host_model_name = re.search(r'model:(\w+)', labels).group(1)
  except AttributeError:
    # TODO(pprabhu): Make this exception a failure.
    logging.exception('Model: name attribute is missing in %s/host_keyval/%s.',
                      dir, keyval.get('hostname'))
    return

  if not _should_upload(build, result_pattern, suite):
    # No need to upload current folder, return.
    return

  parent_job_id = str(keyval['parent_job_id'])

  job_id, package, timestamp = _parse_cts_job_results_file_path(path)

  # Results produced by CTS test list collector are dummy results.
  # They don't need to be copied to APFE bucket which is mainly being used for
  # CTS APFE submission.
  if not _is_test_collector(package):
    # Path: bucket/build/parent_job_id/cheets_CTS.*/job_id_timestamp/
    # or bucket/build/parent_job_id/cheets_GTS.*/job_id_timestamp/
    index = build.find('-release')
    build_with_model_name = ''
    if index == -1:
      logging.info('Not a release build.'
                   'Non release build results can be skipped from offloading')
      return

    # CTS v2 pipeline requires device info in 'board.model' format.
    # e.g. coral.robo360-release, eve.eve-release
    build_with_model_name = (
        build[:index] + '.' + host_model_name + build[index:])

    cts_apfe_gs_suffix = os.path.join(build_with_model_name, parent_job_id,
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
          tar_file.extract(CTS_COMPRESSED_RESULT_TYPES[result_pattern])
          test_result_file = os.path.join(
              path, CTS_COMPRESSED_RESULT_TYPES[result_pattern])
      except tarfile.ReadError as error:
        logging.debug(error)
      except KeyError as error:
        logging.debug(error)

    test_result_file_gz = '%s.gz' % test_result_file
    with open(test_result_file,
              'r') as f_in, (gzip.open(test_result_file_gz, 'w')) as f_out:
      shutil.copyfileobj(f_in, f_out)
    instructions.append({
        'name': 'results:' + test_result_gs_suffix,
        'source': test_result_file_gz,
        'destination': test_result_gs_path,
    })

  return instructions


def _should_upload(build, result_pattern, suite):
  """Check if the result should be uploaded to CTS/GTS buckets.

    @param build: Builder name.
    @param result_pattern: XML result file pattern.
    @param suite: Test suite name.

    @returns: Bool flag indicating whether a valid result.
    """
  if build is None or suite is None:
    return False

  # Not valid if it's not a release build.
  if not re.match(r'(?!trybot-).*-release/.*', build):
    return False

  # Not valid if it's cts result but not 'arc-cts*' or 'test_that_wrapper'
  # suite.
  result_patterns = [CTS_RESULT_PATTERN, CTS_V2_RESULT_PATTERN]
  if result_pattern in result_patterns and not (
      suite.startswith('arc-cts') or suite.startswith('arc-gts') or
      suite.startswith('bvt-arc') or suite.startswith('bvt-perbuild') or
      suite.startswith('cros_test_platform') or
      suite.startswith('test_that_wrapper')):
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


def _parse_job_keyval(job_dir):
  """Parse a file of keyvals.

    @param job_dir: The string directory name of the associated job.
    @return A dictionary representing the keyvals.
    """
  # The "real" job dir may be higher up in the directory tree.
  job_dir = _find_toplevel_job_dir(job_dir)
  if not job_dir:
    return {}  # We can't find a top-level job dir with job keyvals.

  keyval_path = os.path.join(job_dir, 'keyval')
  if os.path.isfile(keyval_path):
    return _read_keyval(keyval_path)
  else:
    return {}


def _find_toplevel_job_dir(start_dir):
  """ Starting from start_dir and moving upwards, find the top-level
    of the job results dir. We can't just assume that it corresponds to
    the actual job.dir, because job.dir may just be a subdir of the "real"
    job dir that autoserv was launched with. Returns None if it can't find
    a top-level dir.
    @param start_dir: starting directing for the upward search"""
  job_dir = start_dir
  while not os.path.exists(os.path.join(job_dir, ".autoserv_execute")):
    if job_dir == "/" or job_dir == '':
      return None
    job_dir = os.path.dirname(job_dir)
  return job_dir


def _read_keyval(path):
  """
    Read a key-value pair format file into a dictionary, and return it.
    Takes either a filename or directory name as input. If it's a
    directory name, we assume you want the file to be called keyval.

    @param path: Full path of the file to read from.
    """
  pattern = r'^([-\.\w]+)=(.*)$'
  keyval = {}
  f = open(path)
  for line in f:
    line = re.sub('#.*', '', line).rstrip()
    if not line:
      continue
    match = re.match(pattern, line)
    if match:
      key = match.group(1)
      value = match.group(2)
      if re.search('^\d+$', value):
        value = int(value)
      elif re.search('^(\d+\.)?\d+$', value):
        value = float(value)
      keyval[key] = value
    else:
      raise ValueError('Invalid format line: %s' % line)
  f.close()
  return keyval


def _parse_host_keyval(job_dir, hostname):
  """
    Parse host keyvals.

    @param job_dir: The string directory name of the associated job.
    @param hostname: The string hostname.

    @return A dictionary representing the host keyvals.

    @raises HostKeyvalError if the host keyval is not found.

    """
  hostinfo_path = os.path.join(job_dir, 'host_info_store', hostname + '.store')
  if not os.path.exists(hostinfo_path):
    raise HostKeyvalError('Host keyval not found')

  labels = _deserialize_labels_from_host_info(hostinfo_path)
  label_string = ','.join(el.replace(':', '%3A') for el in labels)
  return {
      'labels': label_string,
      'platform': _first_label_value_for(labels, 'model'),
  }


def _first_label_value_for(labels, key):
  key = key + ':'
  for l in labels:
    if l.startswith(key):
      return l[len(key):]
  return ''


def _deserialize_labels_from_host_info(path):
  with open(path, 'r') as f:
    info = json.load(f)
  return info['labels']


if __name__ == '__main__':
  exit(main())
