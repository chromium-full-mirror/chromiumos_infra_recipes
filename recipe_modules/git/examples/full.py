# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'dev',
    'git',
]


def RunSteps(api):
  api.git.fetch('remote')
  assert api.git.fetch_ref('remote', 'refs/heads/branch') == 'deadbeef'
  api.git.checkout('master', force=True)
  api.git.cherry_pick('branch')
  api.git.commit_files(['README.md'], 'Updated README\n\nMuch better now.')
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.dev.configure(dryrun=True)
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.git.diff_check('some/file/path')

  with api.git.head_context():
    pass


def GenTests(api):
  yield api.test('basic')

  yield (api.test('detached HEAD') +  #
         api.step_data('git symbolic-ref', retcode=1))
