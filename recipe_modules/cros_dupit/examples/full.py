# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

DEPS = [
    'cros_dupit',
]


def RunSteps(api):
  api.cros_dupit.configure(
      rsync_mirror_address='rsync://mirrors.do.not.exists/distfiles',
      rsync_mirror_rate_limit='1m',
      latest_gs_distfiles_uri='gs://stark-trek/mini-cache/latest_distfiles/',
      all_gs_distfiles_uri='gs://stark-trek/the-ultimate-computer/distfiles/')
  api.cros_dupit.run()


def GenTests(api):
  yield api.test('basic')
