# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/raw_io',
    'git_txn',
]


def RunSteps(api):
  api.git_txn.update_ref('remote', lambda: None, ref='ref', retries=2,
                         automerge=True)
  api.git_txn.update_ref('remote', lambda: False, ref='ref')
  api.git_txn.update_ref_write_file('remote', 'Update file', 'file/path.txt',
                                    'data', ref='ref')


def attempt_git_step(api, attempt, git_subcmd, retcode=0, stdout=None):
  message = 'git transaction'
  if attempt > 1:
    message += ' retry 1 of 1'
  return api.step_data('%s.git %s' % (message, git_subcmd),
                       retcode=retcode, stdout=api.raw_io.output(stdout))


def GenTests(api):
  yield api.test('basic')

  yield api.test('retry_succeed') + attempt_git_step(
      api,
      1,
      'push',
      retcode=1,
      stdout='!	HEAD:refs/fake	[remote rejected]',
  ) + attempt_git_step(
      api,
      2,
      'push',
      stdout='deadbeef2',
  )

  yield api.test('other_failure') + attempt_git_step(
      api,
      1,
      'push',
      retcode=1,
      stdout='!	HEAD:refs/fake	[remote failed]',
  )

  yield api.test('retry_too_many_times') + attempt_git_step(
      api,
      1,
      'push',
      retcode=1,
      stdout='!	HEAD:refs/fake	[remote rejected]',
  ) + attempt_git_step(
      api,
      2,
      'rev-parse',
      stdout='deadbeef2',
  ) + attempt_git_step(
      api,
      2,
      'push',
      retcode=1,
      stdout='!	HEAD:refs/fake	[remote rejected]',
  )

  yield api.test('update_ref_has_diff_has_new_file') + api.step_data(
      'git transaction (3).diff check.git ls-files',
      retcode=1,
  )

  yield api.test('update_ref_has_diff_has_change') + api.step_data(
      'git transaction (3).diff check.git ls-files',
      retcode=0,
  ) + api.step_data('git transaction (3).diff check.git diff', retcode=1)
