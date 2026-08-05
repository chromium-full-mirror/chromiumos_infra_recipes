#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Make sure the modified files are formatted."""

from pathlib import Path
import subprocess
from typing import Iterable, List, Set

EXCLUDED_PATHS = (
    Path('recipes.py').resolve(),
    Path('recipes_release/protos/recipes_autoreleaser.py').resolve(),
)


class NeedsFormattingException(Exception):
  """Exception class for when modified files need formatting."""


def main() -> None:
  """Make sure all modified files are formatted (except excluded paths).

  This script doesn't take any arguments, since `git cl format` automatically
  diffs against the merge-base commit.

  Raises:
    NeedsFormattingException: If formatting fails.
  """
  malformatted_files = get_malformatted_files()
  files_that_need_formatting = without_excluded_paths(malformatted_files)
  if files_that_need_formatting:
    here = Path('.').resolve()
    paths_for_error = [
        str(path.relative_to(here)) for path in files_that_need_formatting
    ]
    raise NeedsFormattingException(
        f'Some files need formatting: {paths_for_error}.\n'
        'Please run: `git cl format --no-clang-format --python')


def get_malformatted_files() -> List[Path]:
  """Determine which files, if any, are not properly formatted.

  For each malformatted file, the stdout of `git cl format ... --diff` will
  include a chunk like:
    --- recipes/annealing.py\t(original)
    +++ recipes/annealing.py\t(reformatted)
    @@ -12,34 +12,34 @@
     This line is the same in both versions.
    -This line is only in the original.
    +This line is only in the reformatted.

  Thus, we can find the files with diffs by parsing only the lines that begin
  with `+++` or `---` (and deduplicating).

  Returns:
    A list of resolved paths to all malformatted files, even if those files are
    in EXCLUDED_FILES.
  """
  stdout = subprocess.run([
      'git', 'cl', 'format', '--presubmit', '--python', '--no-clang-format',
      '--diff'
  ], capture_output=True, check=True).stdout.decode('utf-8')
  paths: Set[Path] = set()
  for line in stdout.split('\n'):
    if line.startswith('---') or line.startswith('+++'):
      paths.add(Path(line.split()[1].strip()).resolve())
  return list(paths)


def without_excluded_paths(paths: Iterable[Path]) -> List[Path]:
  """Return a copy of paths, without any elements of EXCLUDED_PATHS."""
  return_paths = []
  for path in paths:
    if path.resolve() not in EXCLUDED_PATHS:
      return_paths.append(path)
  return return_paths


if __name__ == '__main__':
  main()
