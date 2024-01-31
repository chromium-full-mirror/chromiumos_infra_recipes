# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
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
      gs_topdir_backfill=True)
  api.cros_dupit.run()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DoesNotRun,
                       'get list of files matching additional regex'),
      api.post_process(post_process.DoesNotRun,
                       'add additional regex files to distfiles list'),
      api.post_process(post_process.DoesNotRun,
                       'copy new distfiles to gs.filtering missing symlinks'),
      api.post_process(
          post_process.MustRun,
          'backfill gs distfiles topdir.get list of files in hashed subdirs'),
      api.post_process(
          post_process.DoesNotRun,
          'copy new distfiles to gs.prepare additional regex files for sync'),
      api.post_process(
          post_process.DoesNotRun,
          'copy new distfiles to gs.gsutil upload additional regex files to gs://stark-trek/the-ultimate-computer/distfiles/'
      ),
      api.post_process(
          post_process.DoesNotRun,
          'copy new distfiles to gs.gsutil archive additional regex files to gs://stark-trek/the-ultimate-computer/distfiles-archive/'
      ),
      api.step_data('copy new distfiles to gs.list new distfiles',
                    stdout=api.raw_io.output_text('new_distfile.tar.gz')))

  yield api.test('no-new-distfiles')

  yield api.test(
      'symlink-distfile',
      api.step_data(
          'gsutil list distfiles in '
          'gs://stark-trek/the-ultimate-computer/distfiles/',
          stdout=api.raw_io.output_text('''
gs://stark-trek/the-ultimate-computer/distfiles/exists-in-gs.tar.gz''')),
      api.step_data(
          'list distfiles in rsync://mirrors.do.not.exists/distfiles',
          stdout=api.raw_io.output('''
lrwxrwxrwx 12 2020/02/29 12:34:56 symlink.tar.gz -> dir/symlinked.tar.gz
-rw-r--r-- 12 2020/02/29 12:34:56 exists-in-gs.tar.gz''')),
      api.step_data(
          'list symlink distfiles', stdout=api.raw_io.output('''
1 lrwxrwxrwx Feb 29 12:34 ./symlink.tar.gz -> dir/symlinked.tar.gz''')),
      api.step_data('copy new distfiles to gs.list new distfiles',
                    stdout=api.raw_io.output_text('dir/symlinked.tar.gz')))
