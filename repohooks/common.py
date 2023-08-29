# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common functions to help with custom repohooks."""

from pathlib import Path
from typing import Iterable, List


def to_resolved_paths(string_paths: Iterable[str]) -> List[Path]:
  """Parse the CLI args into a list of modified filepaths.

  This is commonly used to parse the files modified by a commit, passed in from
  PRESUBMIT.cfg as ${PRESUBMIT_FILES}. See documentation at:
  go/cros-preupload#Environment

  Args:
    string_paths: An iterable of strings each containing a filepath, which may
      be relative or absolute. Relative paths will be considered relative to
      the current working directory.

  Returns:
    Resolved, absolute filepaths corresponding to each passed-in string path.
  """
  return [Path(path).resolve() for path in string_paths]
