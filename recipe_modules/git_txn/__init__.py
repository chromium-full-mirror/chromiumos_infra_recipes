# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the git_txn module."""

DEPS = [
    'recipe_engine/file',
    'recipe_engine/step',
    'gerrit',
    'git',
    'repo',
]
