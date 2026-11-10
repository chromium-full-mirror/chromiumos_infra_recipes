#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run unit tests for modified recipe or recipe_module resource directories."""

from pathlib import Path
import subprocess
import sys
from typing import List, Set

import common

REPO_ROOT = Path('.').resolve()
RECIPES_DIR = REPO_ROOT / 'recipes'
MODULES_DIR = REPO_ROOT / 'recipe_modules'
REPOHOOK_TRIGGERS = (
    REPO_ROOT / 'PRESUBMIT.cfg',
    Path(__file__).resolve(),
)


def find_target_tests(modified_paths: List[Path]) -> List[Path]:
  """Return resource unit test scripts affected by `modified_paths`.

  Args:
    modified_paths: Resolved paths of files modified in the commit. If empty or
      if `PRESUBMIT.cfg` or this hook itself was modified, all standalone
      `*_test.py` scripts directly under `recipes/*.resources/` and
      `recipe_modules/*/resources/` are returned.

  Returns:
    Sorted list of standalone resource `*_test.py` file paths to execute.
  """
  run_all = not modified_paths or any(
      path in REPOHOOK_TRIGGERS for path in modified_paths)
  resource_dirs: Set[Path] = set()
  if run_all:
    resource_dirs.update(RECIPES_DIR.glob('*.resources'))
    resource_dirs.update(MODULES_DIR.glob('*/resources'))
  else:
    for path in modified_paths:
      for candidate in (path, *path.parents):
        if candidate.parent == RECIPES_DIR and candidate.name.endswith(
            '.resources'):
          resource_dirs.add(candidate)
          break
        if (candidate.name == 'resources' and
            candidate.parent.parent == MODULES_DIR):
          resource_dirs.add(candidate)
          break
      if path.parent == RECIPES_DIR and path.suffix == '.py':
        sibling_resources = RECIPES_DIR / f'{path.stem}.resources'
        if sibling_resources.is_dir():
          resource_dirs.add(sibling_resources)
      elif MODULES_DIR in path.parents:
        rel_parts = path.relative_to(MODULES_DIR).parts
        if rel_parts:
          module_resources = MODULES_DIR / rel_parts[0] / 'resources'
          if module_resources.is_dir():
            resource_dirs.add(module_resources)

  tests: Set[Path] = set()
  for resource_dir in resource_dirs:
    if resource_dir.is_dir():
      tests.update(resource_dir.glob('*_test.py'))
  return sorted(tests)


def main(argv: List[str]) -> None:
  """Run standalone `vpython3` unit tests for affected resource directories.

  Args:
    argv: Command-line args passed into this script, normally
      `${PRESUBMIT_FILES}` from `PRESUBMIT.cfg`.

  Raises:
    subprocess.CalledProcessError: If any resource unit test fails.
  """
  modified_paths = common.to_resolved_paths(argv)
  for test_path in find_target_tests(modified_paths):
    subprocess.run(['vpython3', '-B', str(test_path)], check=True)


if __name__ == '__main__':
  main(sys.argv[1:])
