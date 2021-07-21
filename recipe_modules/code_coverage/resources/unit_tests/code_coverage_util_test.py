#!/usr/bin/env vpython
# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json
import unittest
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))
import code_coverage_util


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
    self.constants_file = {
        "test": [{
            "src_path":
                "bluetooth",
            "prefix":
                "tmp/portage/chromeos-base/bluetooth-[^/]*/work/bluetooth-[^/]*/bluetooth"
        }, {
            "src_path":
                "biod",
            "prefix":
                "tmp/portage/chromeos-base/biod-[^/]*/work/biod-[^/]*/biod"
        }, {
            "src_path": "",
            "prefix": "/mnt/host/source/src/platform2/"
        }]
    }

  def _getStructuredFile(self, file_names):
    return {
        'data': [{
            'files': [{
                'filename': x
            } for x in file_names]
        }],
        'version': '1.0',
        'type': 'llvm.coverage.json.export'
    }

  def testIgnoresFileNamesThatArentInConstantsFile(self):
    data = self._getStructuredFile(['/path/a.txt', '/path/b.txt'])
    result = code_coverage_util.clean_file_names_in_llvm_coverage_json(
        data, {"test": []}, 'test', 'sarien', 'prepend')
    self.assertListEqual(result['data'][0]['files'], [])

  def testRemapsAllFileNames(self):
    data = self._getStructuredFile([
        '/build/sarien/var/cache/portage/chromeos-base/bluetooth/out/Default/../../../../../../../tmp/portage/chromeos-base/bluetooth-0.0.1-r666/work/bluetooth-0.0.1/bluetooth/common/bluetooth_daemon.h',
        '/build/sarien/var/cache/portage/chromeos-base/bluetooth/out/Default/../../../../../../../tmp/portage/chromeos-base/bluetooth-0.0.1-r666/work/bluetooth-0.0.1/bluetooth/common/dbus_daemon.cc',
        '/build/sarien/tmp/portage/chromeos-base/biod-0.0.1-r2062/work/build/out/Default/../../../biod-0.0.1/biod/biod_config.cc',
        '/build/sarien/var/cache/portage/chromeos-base/lorgnette/out/Default/../../../../../../../../../mnt/host/source/src/platform2/common-mk/testrunner.cc',
    ])
    result = code_coverage_util.clean_file_names_in_llvm_coverage_json(
        data, self.constants_file, 'test', 'sarien', '')

    result_filenames = [x['filename'] for x in result['data'][0]['files']]
    self.assertEqual(len(result_filenames), 4)
    self.assertEqual(
        len([
            x for x in result_filenames
            if x == 'bluetooth/common/bluetooth_daemon.h'
        ]), 1)
    self.assertEqual(
        len([
            x for x in result_filenames
            if x == 'bluetooth/common/dbus_daemon.cc'
        ]), 1)
    self.assertEqual(
        len([x for x in result_filenames if x == 'biod/biod_config.cc']), 1)
    self.assertEqual(
        len([x for x in result_filenames if x == 'common-mk/testrunner.cc']), 1)

  def testRemapsAllFileNamesWithPrepends(self):
    data = self._getStructuredFile([
        '/build/sarien/tmp/portage/chromeos-base/biod-0.0.1-r2062/work/build/out/Default/../../../biod-0.0.1/biod/biod_config.cc'
    ])
    result = code_coverage_util.clean_file_names_in_llvm_coverage_json(
        data, self.constants_file, 'test', 'sarien', '/abc/')
    result_filenames = [x['filename'] for x in result['data'][0]['files']]
    self.assertEqual(
        len([x for x in result_filenames if x == '/abc/biod/biod_config.cc']),
        1)


if __name__ == '__main__':
  unittest.main()
