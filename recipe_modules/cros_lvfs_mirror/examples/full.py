# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'cros_lvfs_mirror',
]



def RunSteps(api):
  api.cros_lvfs_mirror.configure(mirror_address='address', gs_uri='uri')
  api.cros_lvfs_mirror.run()
  assert api.cros_lvfs_mirror.mirror_address == 'address'
  assert api.cros_lvfs_mirror.gs_uri == 'uri'


def GenTests(api):
  yield api.test('basic')
