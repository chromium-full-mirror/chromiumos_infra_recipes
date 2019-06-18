# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'git',
]


def RunSteps(api):
  commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
  api.git.clone('https://mygithost.google.com/somerepo')
  api.git.fetch('remote')
  api.assertions.assertEqual(
      api.git.fetch_ref('remote', 'refs/heads/branch'), commit_id)
  api.git.checkout('master', force=True)
  api.git.merge('branch', 'yeet')
  api.git.cherry_pick('branch')
  api.git.commit_files(['README.md'], 'Updated README\n\nMuch better now.')
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.git.push('origin', 'HEAD:master', capture_stdout=True)
  api.git.diff_check('some/file/path')
  [commit] = api.git.log('START_REF', 'END_REF', limit=30)
  api.assertions.assertEqual(commit.rev, commit_id)
  api.assertions.assertEqual(commit.message, 'message')
  api.git.add('some/file/path')
  api.git.is_reachable('deadbeef')
  api.git.show_file('deadbeef', 'some/path')
  api.git.create_bundle(api.path['start_dir'].join('bundle'), 'HEAD^', 'HEAD')
  api.assertions.assertEqual(
      api.git.get_diff_files('master', 'HEAD'),
      ['a/b/text.txt', 'other_test.txt'])
  api.assertions.assertEqual(
      api.git.get_working_dir_diff_files(),
      ['changed.txt', 'new.txt'])

  with api.git.head_context():
    pass


def GenTests(api):
  yield api.test('basic')

  yield (api.test('show_file_path_not_found') +  #
         api.step_data('git show', retcode=128))

  yield (api.test('detached_HEAD') +  #
         api.step_data('git symbolic-ref', retcode=1))

  yield api.test('diff_check_has_new_file') + api.step_data(
      'diff check.git ls-files',
      retcode=1,
  )
