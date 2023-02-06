# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uploading mappings to the PVS database.
"""

from recipe_engine import post_process

DEPS = ["build_menu"]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.build_menu.configure_builder(
      missing_ok=True), api.build_menu.setup_workspace_and_chroot():
    pass


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess))
