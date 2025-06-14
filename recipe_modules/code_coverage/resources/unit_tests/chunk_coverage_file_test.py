#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import shutil
import sys
import tempfile
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))
import chunk_coverage_file  # pylint: disable=wrong-import-position


class ChunkLlvmCoverageFileTest(unittest.TestCase):

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  @staticmethod
  def coverage_json(coverage_data_size):
    coverage_data = []

    i = 0
    while i < coverage_data_size:
      i += 1
      coverage_data.append({'filename': str(i)})
    return {
        'data': [{
            'files': coverage_data,
        }],
        'type': 'llvm.coverage.json.export',
        'version': '2.0.1',
    }

  @staticmethod
  def read_coverage_data(file_path):
    with open(file_path, encoding='utf-8') as f:
      coverage_json = json.load(f)
      return coverage_json['data'][0]['files']

  def testEmptyCoverage(self):
    coverage_path = os.path.join(self.tmpdir, 'empty_coverage.json')
    with open(coverage_path, 'w', encoding='utf-8') as outfile:
      outfile.write(json.dumps({}))

    dest_dir = tempfile.mkdtemp()
    chunk_coverage_file.chunk(coverage_path, 2, dest_dir, 'LLVM')
    chunk_files = os.listdir(dest_dir)
    self.assertEqual(0, len(chunk_files), 'There should be 0 chunks.')

  def testShouldSplitSuccessfully_1(self):
    coverage_path = os.path.join(self.tmpdir, 'big_coverage.json')
    with open(coverage_path, 'w', encoding='utf-8') as outfile:
      outfile.write(json.dumps(self.coverage_json(4)))
    dest_dir = tempfile.mkdtemp()

    chunk_coverage_file.chunk(coverage_path, 2, dest_dir, 'LLVM')
    chunk_files = [os.path.join(dest_dir, x) for x in os.listdir(dest_dir)]

    self.assertEqual(2, len(chunk_files), 'There should be two chunks.')
    for chunk in chunk_files:
      self.assertEqual(2, len(self.read_coverage_data(chunk)),
                       'Each chunk should have exactly 2 entries')

  def testShouldSplitSuccessfully_2(self):
    coverage_path = os.path.join(self.tmpdir, 'big_coverage.json')
    with open(coverage_path, 'w', encoding='utf-8') as outfile:
      outfile.write(json.dumps(self.coverage_json(5)))

    dest_dir = tempfile.mkdtemp()
    chunk_coverage_file.chunk(coverage_path, 2, dest_dir, 'LLVM')
    chunk_files = [os.path.join(dest_dir, x) for x in os.listdir(dest_dir)]

    self.assertEqual(3, len(chunk_files), 'There should be three chunks.')

    count = 0
    for chunk in chunk_files:
      count += len(self.read_coverage_data(chunk))

    self.assertEqual(5, count)

  def testShouldSplitSuccessfully_3(self):
    coverage_path = os.path.join(self.tmpdir, 'big_coverage.json')

    with open(coverage_path, 'w', encoding='utf-8') as outfile:
      outfile.write(json.dumps(self.coverage_json(5)))

    dest_dir = tempfile.mkdtemp()

    chunk_coverage_file.chunk(coverage_path, 10, dest_dir, 'LLVM')

    chunk_files = [os.path.join(dest_dir, x) for x in os.listdir(dest_dir)]

    self.assertEqual(1, len(chunk_files), 'There should be one chunks.')

    count = 0
    for chunk in chunk_files:
      count += len(self.read_coverage_data(chunk))

    self.assertEqual(5, count)

  def testShouldNotChunkForNonLLVMFile(self):
    coverage_path = os.path.join(self.tmpdir, 'lcov_coverage.json')

    with open(coverage_path, 'w', encoding='utf-8') as outfile:
      outfile.write(json.dumps({}))

    dest_dir = tempfile.mkdtemp()

    chunk_coverage_file.chunk(coverage_path, 10, dest_dir, 'LCOV')
    chunk_files = os.listdir(dest_dir)

    self.assertEqual(1, len(chunk_files), 'There should be one chunks.')
    self.assertEqual('lcov_coverage.json', chunk_files[0])


if __name__ == '__main__':
  unittest.main()
