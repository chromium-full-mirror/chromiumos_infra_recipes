#!/usr/bin/env vpython3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for clean_coverage_file."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))

import clean_coverage_file  # pylint: disable=wrong-import-position
import code_coverage_util  # pylint: disable=wrong-import-position


class CleanFilePathsTest(unittest.TestCase):

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.path_to_coverage_file = os.path.join(self.tmpdir, 'cov')
    self.path_to_cons_file = os.path.join(self.tmpdir, 'cons')
    self.path_to_out_file = os.path.join(self.tmpdir, 'out')

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  @staticmethod
  def _write_to_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
      f.write(content)

  @staticmethod
  def _read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
      return f.read()

  @staticmethod
  def _read_file_json(path):
    with open(path, 'r', encoding='utf-8') as f:
      return json.load(f)

  @mock.patch.object(code_coverage_util, 'is_valid_lcov_coverage_file')
  def test_writes_data_as_is_when_is_valid_lcov_coverage_file_returns_false(
      self, mock_is_valid_lcov_coverage_file):
    mock_is_valid_lcov_coverage_file.return_value = False
    self._write_to_file(self.path_to_coverage_file, 'abc')
    self._write_to_file(self.path_to_cons_file, '[]')

    clean_coverage_file.clean_file_paths(self.path_to_coverage_file,
                                         self.path_to_cons_file,
                                         self.path_to_out_file, True)

    self.assertEqual('abc', self._read_file(self.path_to_out_file))

  @mock.patch.object(code_coverage_util, 'clean_file_names_in_lcov_coverage')
  @mock.patch.object(code_coverage_util, 'is_valid_lcov_coverage_file')
  def test_writes_cleaned_results(self, mock_is_valid_lcov_coverage_file,
                                  mock_clean_file_names_in_lcov_coverage):
    mock_is_valid_lcov_coverage_file.return_value = True
    mock_clean_file_names_in_lcov_coverage.return_value = 'SF:cleaned.c\n'
    self._write_to_file(self.path_to_coverage_file, 'SF:dirty.c\n')
    self._write_to_file(self.path_to_cons_file, '[]')

    clean_coverage_file.clean_file_paths(self.path_to_coverage_file,
                                         self.path_to_cons_file,
                                         self.path_to_out_file, True)

    self.assertEqual('SF:cleaned.c\n', self._read_file(self.path_to_out_file))

  def test_cleans_ti50_lcov_to_repo_relative_paths(self):
    real_mapping = os.path.abspath(
        os.path.join(THIS_DIR, os.pardir, 'path_mapping.json'))
    raw_lcov = '\n'.join([
        'SF:src/platform/ti50/common/libs/crypto/src/lib.rs',
        'DA:10,1',
        'end_of_record',
        'SF:/mnt/host/source/src/platform/ti50/common/capsules/src/alarm.rs',
        'DA:20,0',
        'end_of_record',
        'SF:src/platform/ti50/ports/tpm2_server/src/lib.rs',
        'DA:5,2',
        'end_of_record',
        'SF:src/platform/pinweaver/eal/ti50/src/lib.rs',
        'DA:8,1',
        'end_of_record',
        'SF:src/platform/gsc-utils/boot_param/boot_param.c',
        'DA:12,3',
        'end_of_record',
        'SF:src/third_party/tock/tock/kernel/src/grant.rs',
        'DA:15,4',
        'end_of_record',
        'SF:src/third_party/tock/libtock-rs/core/src/lib.rs',
        'DA:3,1',
        'end_of_record',
        'SF:src/third_party/ms-tpm-20-ref/TPMCmd/tpm/src/CryptUtil.c',
        'DA:42,1',
        'end_of_record',
        '',
    ])
    self._write_to_file(self.path_to_coverage_file, raw_lcov)

    clean_coverage_file.clean_file_paths(self.path_to_coverage_file,
                                         real_mapping, self.path_to_out_file,
                                         False)

    expected_lcov = '\n'.join([
        'SF:libs/crypto/src/lib.rs',
        'DA:10,1',
        'end_of_record',
        'SF:capsules/src/alarm.rs',
        'DA:20,0',
        'end_of_record',
        'SF:src/lib.rs',
        'DA:5,2',
        'end_of_record',
        'SF:eal/ti50/src/lib.rs',
        'DA:8,1',
        'end_of_record',
        'SF:boot_param/boot_param.c',
        'DA:12,3',
        'end_of_record',
        'SF:kernel/src/grant.rs',
        'DA:15,4',
        'end_of_record',
        'SF:core/src/lib.rs',
        'DA:3,1',
        'end_of_record',
        'SF:TPMCmd/tpm/src/CryptUtil.c',
        'DA:42,1',
        'end_of_record',
        '',
    ])
    self.assertEqual(expected_lcov, self._read_file(self.path_to_out_file))


if __name__ == '__main__':
  unittest.main()
