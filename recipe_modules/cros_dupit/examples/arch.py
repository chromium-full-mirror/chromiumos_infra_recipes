# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/raw_io',
    'cros_dupit',
]



def RunSteps(api):
  api.cros_dupit.configure(
      rsync_mirror_address='rsync://mirrors.do.not.exists/distfiles',
      rsync_mirror_rate_limit='1m',
      gs_distfiles_uri='gs://stark-trek/the-ultimate-computer/distfiles/',
      ignore_missing_args=True, filter_missing_links=True,
      regex_for_archival_sync='^.+[.](db|db.tar.gz|files|files.tar.gz)$',
      gs_uri_for_archival_sync='gs://stark-trek/the-ultimate-computer/distfiles-archive/',
      path_datetime_for_archival_sync='%Y/%m/%d/%H%M%S%f/')
  api.cros_dupit.run()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.MustRun,
                       'get list of files matching additional regex'),
      api.post_process(post_process.MustRun,
                       'add additional regex files to distfiles list'),
      api.post_process(post_process.MustRun,
                       'copy new distfiles to gs.filtering missing symlinks'),
      api.post_process(
          post_process.DoesNotRun,
          'backfill gs distfiles topdir.get list of files in hashed subdirs'),
      api.post_process(
          post_process.MustRun,
          'copy new distfiles to gs.prepare additional regex files for sync'),
      api.post_process(
          post_process.MustRun,
          'copy new distfiles to gs.gsutil upload additional regex files to gs://stark-trek/the-ultimate-computer/distfiles/'
      ),
      api.post_process(
          post_process.StepSuccess,
          'copy new distfiles to gs.gsutil archive additional regex files to gs://stark-trek/the-ultimate-computer/distfiles-archive/2012/05/14/125321500000/'
      ),
      api.post_process(
          post_process.StepSuccess,
          'copy new distfiles to gs.gsutil create donefile at gs://stark-trek/the-ultimate-computer/distfiles-archive/2012/05/14/125321500000/.dupit_done'
      ),
      api.step_data('copy new distfiles to gs.list new distfiles',
                    stdout=api.raw_io.output_text('new_distfile.tar.gz')),
  )
