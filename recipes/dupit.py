# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing remote, distributed tarballs to our local cache."""

DEPS = [
    'cros_dupit',
]


def RunSteps(api):
  api.cros_dupit.configure(
      rsync_mirror_address='rsync://mirrors.rit.edu/gentoo/distfiles',
      rsync_mirror_rate_limit='1m',
      gs_distfiles_uri='gs://chromeos-mirror/gentoo/distfiles/')
  api.cros_dupit.run()


def GenTests(api):
  yield api.test('basic')
