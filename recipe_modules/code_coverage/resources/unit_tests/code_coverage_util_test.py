#!/usr/bin/env vpython3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for code_coverage_util."""

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
    with open(
        os.path.join(__RESOURCES_DIR__, 'path_mapping.json'), 'r',
        encoding='utf-8') as constant_file:
      self.path_mappings = json.load(constant_file)

  def testCleanFileName(self):
    samples = [
        ('/mnt/host/source/src/platform/ec/zephyr/app/main.c',
         'src/platform/ec/zephyr/app/main.c', 'zephyr/app/main.c'),
        ('/mnt/host/source/src/third_party/zephyr/main/subsys/test.c',
         'src/third_party/zephyr/main/subsys/test.c', 'subsys/test.c'),
    ]
    for artifact, expected_abs, expected_rel in samples:
      with self.subTest(artifact=artifact):
        mapped = code_coverage_util.clean_file_name(artifact,
                                                    self.path_mappings)
        self.assertEqual(mapped, (expected_abs, expected_rel))


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
