# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'dev',
    'git',
]


def RunSteps(api):
  commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
  api.git.fetch('remote')
  assert api.git.fetch_ref('remote', 'refs/heads/branch') == commit_id
  api.git.checkout('master', force=True)
  api.git.cherry_pick('branch')
  api.git.commit_files(['README.md'], 'Updated README\n\nMuch better now.')
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.dev.configure(dryrun=True)
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.git.diff_check('some/file/path')
  [commit] = api.git.log('START_REF', 'END_REF')
  assert commit.rev == commit_id and commit.message == 'message'
  api.git.add('some/file/path')
  api.git.is_reachable('deadbeef')
  api.git.show_file('deadbeef', 'some/path')
  api.git.create_bundle(api.path['start_dir'].join('bundle'), 'HEAD^', 'HEAD')
  api.git.position_num()

  with api.git.head_context():
    pass


def GenTests(api):
  yield api.test('basic')

  yield (api.test('show_file path not found') +  #
         api.step_data('git show', retcode=128))

  yield (api.test('detached HEAD') +  #
         api.step_data('git symbolic-ref', retcode=1))

  yield api.test('diff_check has new file') + api.step_data(
      'diff check.git ls-files',
      retcode=1,
  )

  yield (api.test('no git position footer') +  #
         api.step_data('git_footers.py', retcode=1))
