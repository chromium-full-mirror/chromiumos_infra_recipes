# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from recipe_engine import recipe_test_api


def _read_test_file(filename):
  """Read the content of a file in this directory.

  Args:
    filename (str): The basename of the file (located in this directory) to
        read.

  Returns:
    (str): The contents of the file.
  """
  with open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                         filename)) as f:
    return f.read().strip()


# Test data for valid paygen source (actually configured at one point).
TEST_SRC_LS_OUTPUT_TEXT = _read_test_file('test_src_ls_output.txt')

# Test data for valid paygen target (actually configured at one point).
TEST_TGT_LS_OUTPUT_TEXT = _read_test_file('test_tgt_ls_output.txt')

# Test data for paygen target missing all except an unsigned test image.
TEST_TGT_LS_OUTPUT_MISSING_TEST = """
gs://chromeos-releases/beta-channel/coral/13505.15.0/ChromeOS-test-R87-13505.15.0-coral.tar.xz
"""


class CrosStorageTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the CrosStorage module."""

  TEST_SRC_LS_OUTPUT_TEXT = TEST_SRC_LS_OUTPUT_TEXT
  TEST_TGT_LS_OUTPUT_TEXT = TEST_TGT_LS_OUTPUT_TEXT
  TEST_TGT_LS_OUTPUT_MISSING_TEST = TEST_TGT_LS_OUTPUT_MISSING_TEST

  def test_listing(self, step_name='discover gs artifacts.gsutil list',
                   test_data=TEST_SRC_LS_OUTPUT_TEXT):
    """Returns a string of google storage ls test data."""
    return self.step_data(step_name,
                          stdout=self.m.raw_io.output_text(test_data))
