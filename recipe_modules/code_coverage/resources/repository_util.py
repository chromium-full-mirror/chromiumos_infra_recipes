# -*- coding: utf-8 -*-
# Lint as: python2, python3
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to retrieve the last changed revision of files in the checkout.

It parses the DEPS file to look for dependency repositories, and runs "git log"
to get the last changed revision of files.
"""

import logging
import os
import subprocess
import time


class _Timer(object):

  def __init__(self):
    self._time = None

  def Start(self):
    self._time = time.time()

  def End(self, msg):
    new_time = time.time()
    elapsed_time = new_time - self._time
    logging.info('%s took %.0f seconds', msg, elapsed_time)


def _retrieve_revision_from_git(root_dir, path):
  """Returns the path, git hash, and last changed timestamp of the given file.

  Args:
    root_dir (str): System absolute path to the root checkout.
    path (str): Source absolute path to the file to retrieve the revision.

  Returns:
    A tuple of three elements:
      1. Source absolute path to the file.
      2. Git hash of the commit when the file was most recently updated.
      3. Time stamp of the commit when the file was most recently updated.
  """
  assert path.startswith('//'), '%s is expected to start with //' % path
  file_dir = os.path.dirname(os.path.join(root_dir, path[2:]))
  file_name = os.path.basename(path[2:])
  try:
    path_in_sub_repo = subprocess.check_output(
        ['git', 'rev-parse', '--show-prefix'], cwd=file_dir).strip().rstrip('/')

    checkout_dir = file_dir
    if path_in_sub_repo != '':
      checkout_dir = checkout_dir[:-len(path_in_sub_repo)]
    git_output = subprocess.check_output([
        'git', 'log', '-n', '1', '--pretty=format:%H:%ct', '--',
        os.path.join(path_in_sub_repo, file_name)
    ], cwd=checkout_dir)

    lines = git_output.splitlines()
    assert len(lines) == 1, 'More than one line output.'

    parts = lines[0].split(':')
    assert len(parts) == 2, 'not in format "git_hash:timestamp"'

    return path, parts[0], int(parts[1])
  except (subprocess.CalledProcessError, AssertionError):
    print('Failed to retrieve revision for: %r' % (path))  #pylint: disable=superfluous-parens
    return None


def get_file_revisions(root_dir, file_paths):
  timer = _Timer()
  timer.Start()

  all_result = {}
  for path in file_paths:
    result = _retrieve_revision_from_git(root_dir, path)
    if not result:
      continue
    path, git_hash, timestamp = result
    all_result[path] = (git_hash, timestamp)

  timer.End('_retrieve_revision_from_git')
  return all_result


def add_git_revisions_to_coverage_files_metadata(files_coverage_data, src_path):
  """Add git revisions to a list File in coverage metadata format.

  Coverage metadata format:
  https://chromium.googlesource.com/infra/infra/+/HEAD/appengine/findit/model/proto/code_coverage.proto

  Args:
    files_coverage_data (list): A list of File in coverage metadata format, and
                                it is going to be mutated by this function.
    src_path (str): Absolute path to the source root.
  """
  logging.info('Retrieving file git metadata...')
  start_time = time.time()

  all_files = [file_record['path'] for file_record in files_coverage_data]
  file_git_metadata = get_file_revisions(src_path, all_files)
  for file_record in files_coverage_data:
    git_metadata = file_git_metadata.get(file_record['path'])
    if not git_metadata:
      logging.warn('Failed to retrive git metadata for %s', file_record['path'])
      continue

    file_record['revision'], file_record['timestamp'] = git_metadata

  minutes = (time.time() - start_time) / 60
  logging.info(
      'Retrieving and filling in git metadata for %d files took %.0f '
      'minutes', len(all_files), minutes)
