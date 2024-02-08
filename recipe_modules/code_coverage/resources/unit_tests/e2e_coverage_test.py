#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to test e2e coverage uploads."""

from datetime import date
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import json

__THIS_DIR__ = os.path.dirname(os.path.abspath(__file__))
__RESOURCES_DIR__ = str(Path(__file__).parent.parent.resolve())
sys.path.insert(0, os.path.abspath(os.path.join(__THIS_DIR__, os.pardir)))
import e2e_coverage  # pylint: disable=wrong-import-position


class E2ECoverageTest(unittest.TestCase):
  """Test file for e2e_coverage.py."""

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test_upload_metadata(self):
    """Test that we add metadata correctly."""
    path = self.tmpdir + '/metadata.json'
    e2e_coverage.write_metadata('bucket', 'path', 'brya',
                                'R123-15766.0.0-94241', path)
    self.assertEqual(len(os.listdir(self.tmpdir)), 1)

    with open(path, encoding='utf-8') as f:
      content = json.loads(f.read())
      self.assertEqual(content['artifacts_bucket'], 'bucket')
      self.assertEqual(content['artifacts_path'], 'path')
      self.assertEqual(content['board'], 'brya')
      self.assertEqual(content['version'], 'R123-15766.0.0-94241')
      self.assertEqual(content['date'], date.today().isoformat())


if __name__ == '__main__':
  unittest.main()
