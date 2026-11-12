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

  def testCleanLcovApFirmwarePaths(self):
    test_lcov = (
        'TN:\n'
        'SF:/mnt/host/source/src/third_party/coreboot/src/lib/bootblock.c\n'
        'DA:10,1\n'
        'SF:src/third_party/coreboot/payloads/libpayload/libc/string.c\n'
        'DA:5,1\n'
        'SF:/mnt/host/source/src/platform/depthcharge/src/vboot/main.c\n'
        'DA:15,1\n'
        'SF:/build/brya/tmp/portage/sys-boot/depthcharge-0.0.1-r1/work/'
        'depthcharge-0.0.1/src/vboot/main.c\n'
        'DA:20,1\n'
        'SF:src/platform/depthcharge/src/drivers/storage/storage.c\n'
        'DA:30,1\n'
        'SF:/mnt/host/source/src/platform/vboot_reference/firmware/lib/crc8.c\n'
        'DA:40,1\n'
        'SF:src/platform/vboot_reference/futility/futility.c\n'
        'DA:50,1\n'
        'SF:/usr/include/stdio.h\n'
        'DA:60,1\n'
        'end_of_record\n')
    expected_abs = (
        'TN:\n'
        'SF:src/third_party/coreboot/src/lib/bootblock.c\n'
        'DA:10,1\n'
        'SF:src/third_party/coreboot/payloads/libpayload/libc/string.c\n'
        'DA:5,1\n'
        'SF:src/platform/depthcharge/src/vboot/main.c\n'
        'DA:15,1\n'
        'SF:src/platform/depthcharge/src/vboot/main.c\n'
        'DA:20,1\n'
        'SF:src/platform/depthcharge/src/drivers/storage/storage.c\n'
        'DA:30,1\n'
        'SF:src/platform/vboot_reference/firmware/lib/crc8.c\n'
        'DA:40,1\n'
        'SF:src/platform/vboot_reference/futility/futility.c\n'
        'DA:50,1\n'
        'SF:/tmp/unknown_file\n'
        'DA:60,1\n'
        'end_of_record\n')
    expected_rel = ('TN:\n'
                    'SF:src/lib/bootblock.c\n'
                    'DA:10,1\n'
                    'SF:payloads/libpayload/libc/string.c\n'
                    'DA:5,1\n'
                    'SF:src/vboot/main.c\n'
                    'DA:15,1\n'
                    'SF:src/vboot/main.c\n'
                    'DA:20,1\n'
                    'SF:src/drivers/storage/storage.c\n'
                    'DA:30,1\n'
                    'SF:firmware/lib/crc8.c\n'
                    'DA:40,1\n'
                    'SF:futility/futility.c\n'
                    'DA:50,1\n'
                    'SF:/tmp/unknown_file\n'
                    'DA:60,1\n'
                    'end_of_record\n')
    with self.subTest(to_absolute_path=True):
      self.assertEqual(
          code_coverage_util.clean_file_names_in_lcov_coverage(
              test_lcov, self.path_mappings, to_absolute_path=True),
          expected_abs)
    with self.subTest(to_absolute_path=False):
      self.assertEqual(
          code_coverage_util.clean_file_names_in_lcov_coverage(
              test_lcov, self.path_mappings, to_absolute_path=False),
          expected_rel)


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
