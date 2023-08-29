#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""If infra/config/recipes.cfg was modified, check that it's good JSON."""

import json
from pathlib import Path
import sys
from typing import List

import common

RECIPES_CFG_PATH = Path('infra/config/recipes.cfg').resolve()


def main(argv: List[str]) -> None:
  """If recipes.cfg is among the passed-in files, make sure it parses as JSON.

  Args:
    argv: Command-line args passed into this script. Normally each arg should
      be a relative path to a modified file.

  Raises:
    json.JSONDecodeError: If recipes.cfg was modified and isn't good JSON.
  """
  modified_paths = common.to_resolved_paths(argv)
  if RECIPES_CFG_PATH in modified_paths:
    with RECIPES_CFG_PATH.open(encoding='utf-8') as f:
      json.load(f)


if __name__ == '__main__':
  main(sys.argv[1:])
