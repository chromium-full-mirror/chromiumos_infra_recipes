#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to test e2e coverage uploads."""

import os
import shutil
import tempfile
import unittest
import json

import e2e_coverage


class E2ECoverageTest(unittest.TestCase):
  """Test file for e2e_coverage.py."""

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test_upload_metadata(self):
    """Test that we add metadata correctly."""
    e2e_coverage.write_metadata('bucket', 'path', self.tmpdir)
    files = os.listdir(self.tmpdir)
    self.assertEqual(len(files), 1)

    metadata_file = files[0]
    content = json.loads(metadata_file)
    self.assertEqual(content['artifacts_bucket'], 'bucket')
    self.assertEqual(content['artifacts_path'], 'path')
