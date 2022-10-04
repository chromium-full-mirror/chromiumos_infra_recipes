#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import csv
import json
import os
from pathlib import Path
import sys
import unittest

__THIS_DIR__ = os.path.dirname(os.path.abspath(__file__))
__RESOURCES_DIR__ = str(Path(__file__).parent.parent.resolve())
sys.path.insert(0, os.path.abspath(os.path.join(__THIS_DIR__, os.pardir)))
import code_coverage_util  # pylint: disable=wrong-import-position


class IsValidLlvmCoverageJsonTest(unittest.TestCase):

  def testShouldReturnFalseIfDataIsInvalidJson(self):
    result = code_coverage_util.is_valid_llvm_coverage_json_file('')
    self.assertFalse(result)

  def testShouldReturnTrueWhenDataIsInCoverageLlvmFormat(self):
    result = code_coverage_util.is_valid_llvm_coverage_json_file(
        json.dumps({
            'data': [],
            'type': 'llvm.coverage.json.export',
            'version': '1.0'
        }))
    self.assertTrue(result)


class CleanFileNamesInLlvmCoverageJsonTest(unittest.TestCase):

  def setUp(self):
    with open(os.path.join(__RESOURCES_DIR__, "path_mapping.json"),
              'r') as constant_file:
      self.path_mappings = json.load(constant_file)

  def testCleanFileName(self):
    # expected tuples of (artifact, absolute_path, relative_path)
    expectations = []
    with open(
        os.path.join(__THIS_DIR__, 'path_mapping_test_data.csv'),
        newline='') as f:
      reader = csv.reader(f)
      expectations = [(row[0], row[1], row[2]) for row in reader if len(row) > 0
                     ]

    # real tuples of (artifact, absolute_path, relative_path)
    real_outputs = []
    for row in expectations:
      mapped = code_coverage_util.clean_file_name(row[0], self.path_mappings)
      if mapped:
        real_outputs.append((row[0], mapped[0], mapped[1]))
    self.assertEqual(expectations, real_outputs)


class CreateLlvmCoverageJsonTest(unittest.TestCase):

  def testLlvmCoverageJson(self):
    filename = '/path/to/src/program.cc'
    coverage_data = [{'filename': filename}]
    coverage_json = code_coverage_util.create_llvm_coverage_json(coverage_data)
    self.assertEqual(filename, coverage_json['data'][0]['files'][0]['filename'])
    self.assertEqual(1, len(coverage_json['data']))
    self.assertEqual(1, len(coverage_json['data'][0]['files']))


if __name__ == '__main__':
  unittest.main()
