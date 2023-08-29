#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""If the recipes release directory was modified, run its unit tests."""

from pathlib import Path
import subprocess
import sys
from typing import List

import common

RECIPES_RELEASE_DIR = Path('./recipes_release').resolve()


def main(argv: List[str]) -> None:
  """If the recipes release directory was modified, run its unit tests.

  Args:
    argv: Command-line args passed into this script. Normally each arg should
      be a relative path to a modified file.

  Raises:
    subprocess.CalledProcessError: If unit tests fail.
  """
  modified_paths = common.to_resolved_paths(argv)
  if is_any_path_in_recipes_release_dir(modified_paths):
    run_recipes_release_unit_tests()


def is_any_path_in_recipes_release_dir(paths: List[Path]) -> bool:
  """Return whether any of `paths` is within the recipes release directory."""
  # TODO(b/298033556): Once we're on py3.9+, check subpaths with:
  # path.is_relative_to(RECIPES_RELEASE_DIR)
  return any(RECIPES_RELEASE_DIR in path.parents for path in paths)


def run_recipes_release_unit_tests() -> None:
  """Run unit tests for the recipes release directory.

  Raises:
    subprocess.CalledProcessError: If unit tests fail.
  """
  subprocess.run(['./recipes_release/bin/run_tests'], check=True)


if __name__ == '__main__':
  main(sys.argv[1:])
