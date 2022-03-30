# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_lvfs_mirror',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.cros_lvfs_mirror.configure(mirror_address='address', gs_uri='uri')
  api.cros_lvfs_mirror.run()
  assert api.cros_lvfs_mirror.mirror_address == 'address'
  assert api.cros_lvfs_mirror.gs_uri == 'uri'


def GenTests(api):
  yield api.test('basic')
