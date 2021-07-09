#!/usr/bin/env vpython
# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import os
import shutil
import sys
import tempfile
import unittest
import json

import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))

import clean_coverage_file
import code_coverage_util


class CleanFilePathsTest(unittest.TestCase):

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.path_to_coverage_file = os.path.join(self.tmpdir, 'cov')
    self.path_to_cons_file = os.path.join(self.tmpdir, 'cons')
    self.path_to_out_file = os.path.join(self.tmpdir, 'out')

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _write_to_file(self, path, content):
    with open(path, 'w') as f:
      f.write(content)

  def _read_file(self, path):
    with open(path, 'r') as f:
      return f.read()

  def _read_file_json(self, path):
    with open(path, 'r') as f:
      return json.load(f)

  @mock.patch.object(code_coverage_util, 'is_valid_llvm_coverage_json_file')
  def test_writes_data_as_is_when_is_valid_llvm_coverage_json_file_returns_false(
      self, mock_is_valid_llvm_coverage_json_file):
    mock_is_valid_llvm_coverage_json_file.return_value = False
    self._write_to_file(self.path_to_coverage_file, 'abc')
    self._write_to_file(self.path_to_cons_file, '{"test": []}')

    clean_coverage_file._clean_file_paths(self.path_to_coverage_file,
                                          self.path_to_cons_file,
                                          self.path_to_out_file, 'test',
                                          'sarien', '')

    self.assertEqual('abc', self._read_file(self.path_to_out_file))

  @mock.patch.object(code_coverage_util,
                     'clean_file_names_in_llvm_coverage_json')
  @mock.patch.object(code_coverage_util, 'is_valid_llvm_coverage_json_file')
  def test_writes_cleaned_results(self, mock_is_valid_llvm_coverage_json_file,
                                  mock_clean_file_names_in_llvm_coverage_json):
    mock_is_valid_llvm_coverage_json_file.return_value = 123123
    mock_clean_file_names_in_llvm_coverage_json.return_value = {
        'test': "cleaned"
    }
    self._write_to_file(self.path_to_coverage_file,
                        json.dumps({'test': "dirty"}))
    self._write_to_file(self.path_to_cons_file, json.dumps({'project': "[]"}))

    clean_coverage_file._clean_file_paths(self.path_to_coverage_file,
                                          self.path_to_cons_file,
                                          self.path_to_out_file, 'project',
                                          'sarien', '')

    self.assertDictEqual({'test': 'cleaned'},
                         self._read_file_json(self.path_to_out_file))


if __name__ == '__main__':
  unittest.main()
