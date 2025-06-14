# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility methods available to recipes and recipe modules.

"""

import os


def read_test_file(filename: str, fdir: str) -> str:
  """Read the content of a file in a directory.

  Args:
    filename: The basename of the file (located in this directory) to read.
    fdir: The directory of the file, consumers might pass in `__file__`.

  Returns:
    The contents of the file, stripped.
  """
  with open(
      os.path.join(os.path.abspath(os.path.dirname(fdir)), filename),
      encoding='utf-8') as f:
    return f.read().strip()
