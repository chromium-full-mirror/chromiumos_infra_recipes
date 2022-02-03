# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing to our local cache LVFS files (https://fwupd.org/)."""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'cros_lvfs_mirror',
]


def RunSteps(api):
  api.cros_lvfs_mirror.configure(
      mirror_address='https://cdn.fwupd.org/downloads',
      gs_uri='gs://chromeos-localmirror/lvfs')
  api.cros_lvfs_mirror.run()


def GenTests(api):
  yield api.test('basic')
