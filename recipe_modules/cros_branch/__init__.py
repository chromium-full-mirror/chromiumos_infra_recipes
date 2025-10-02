# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The `cros_branch` module provides API for using the `branch_util` tool.

This tool is utilized for managing branches within a ChromeOS environment,
offering functionalities such as creating, renaming, and deleting branches.
"""

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_version',
    'gobin',
]

from .api import CrosBranchApi as API
