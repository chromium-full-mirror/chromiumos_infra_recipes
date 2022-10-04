#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys
import unittest

import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))

import repository_util  # pylint: disable=wrong-import-position


class RepositoryUtilTest(unittest.TestCase):

  @mock.patch('repository_util.subprocess.check_output', autospec=True)
  def test_get_file_revisions(self, mock_subprocess):

    def mock_subprocess_side_effect(commands, cwd):
      cwd = os.path.normpath(cwd)
      if commands == ['git', 'rev-parse', '--show-prefix']:
        if cwd == '/src/repo/package':
          return 'package/'
        if cwd == '/src/dir1/repo':
          return ''
      elif commands[:-1] == [
          'git', 'log', '-n', '1', '--pretty=format:%H:%ct', '--'
      ]:
        if commands[-1] == 'package/file1.cc' and cwd == '/src/repo':
          return 'file1hash:12345'
        if commands[-1] == 'file2.cc' and cwd == '/src/dir1/repo':
          return 'file2hash:12345'

      assert False, 'Unexpected subprocess call'
      return ''

    mock_subprocess.side_effect = mock_subprocess_side_effect

    file_revisions = repository_util.get_file_revisions(
        '/src', ['//repo/package/file1.cc', '//dir1/repo/file2.cc'])

    expected_file_revisions = {
        '//repo/package/file1.cc': ('file1hash', 12345),
        '//dir1/repo/file2.cc': ('file2hash', 12345)
    }
    self.assertDictEqual(expected_file_revisions, file_revisions)

  @mock.patch.object(repository_util, 'get_file_revisions', autospec=True)
  def test_add_git_revisions_to_coverage_files_metadata(
      self, mock_get_file_revisions):
    mock_get_file_revisions.return_value = {
        '//dir1/file1.cc': ('hash1', 1234),
        '//dir2/file2.cc': ('hash2', 5678),
    }

    coverage_files_data = [{'path': '//dir1/file1.cc'}]
    repository_util.add_git_revisions_to_coverage_files_metadata(
        coverage_files_data, '/src_path')
    expected_coverage_files_data = [{
        'path': '//dir1/file1.cc',
        'revision': 'hash1',
        'timestamp': 1234,
    }]
    self.assertListEqual(expected_coverage_files_data, coverage_files_data)


if __name__ == '__main__':
  unittest.main()
