# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/raw_io',
    'cros_dupit',
]

from recipe_engine import post_process


def RunSteps(api):
  api.cros_dupit.configure(
      rsync_mirror_address='rsync://mirrors.do.not.exists/distfiles',
      rsync_mirror_rate_limit='1m',
      gs_distfiles_uri='gs://stark-trek/the-ultimate-computer/distfiles/',
      ignore_missing_args=True, filter_missing_links=True)
  api.cros_dupit.run()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.MustRun,
                       'copy new distfiles to gs.filtering missing symlinks'),
      api.step_data('copy new distfiles to gs.list new distfiles',
                    stdout=api.raw_io.output_text('new_distfile.tar.gz')),
  )
