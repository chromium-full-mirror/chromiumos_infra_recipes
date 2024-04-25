# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'recipe_engine/context',
    'recipe_engine/raw_io',
    'src_state',
    'git_txn',
]



def RunSteps(api):
  with api.context(cwd=api.src_state.workspace_path / 'src/project'):
    api.git_txn.update_ref('remote', lambda: None, ref='ref', retries=1)
    api.git_txn.update_ref('remote', lambda: False, ref='ref')

    # Normal run
    api.git_txn.update_ref_write_files('remote', 'Update file',
                                       [('file/path.txt', 'data')], ref='ref')
    # Empty of lists
    api.git_txn.update_ref_write_files('remote', 'Update file', [], ref='ref')


def GenTests(api):

  def attempt_git_step(attempt, git_subcmd, retcode=0, stdout=None):
    message = 'update ref.git transaction'
    if attempt > 1:
      message += ' attempt 1 of 2'
    return api.step_data('%s.git %s' % (message, git_subcmd), retcode=retcode,
                         stdout=api.raw_io.output_text(stdout))

  yield api.test('basic')

  yield api.test(
      'retry-succeed',
      attempt_git_step(1, 'push', retcode=1,
                       stdout='! HEAD:refs/fake [remote rejected]'),
      attempt_git_step(2, 'push', stdout='deadbeef2'))

  yield api.test(
      'other-failure',
      attempt_git_step(1, 'push', retcode=1,
                       stdout='! HEAD:refs/fake [remote failed]'),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'retry-too-many-times',
      attempt_git_step(1, 'push', retcode=1,
                       stdout='! HEAD:refs/fake [remote rejected]'),
      attempt_git_step(
          2,
          'rev-parse',
          stdout='deadbeef2',
      ),
      attempt_git_step(2, 'push', retcode=1,
                       stdout='! HEAD:refs/fake [remote rejected]'),
      attempt_git_step(
          3,
          'rev-parse',
          stdout='deadbeef22',
      ),
      attempt_git_step(3, 'push', retcode=1,
                       stdout='! HEAD:refs/fake [remote rejected]'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'update-ref-has-diff-has-new-file',
      api.step_data('update ref (3).git transaction.diff check.git ls-files',
                    retcode=1))

  yield api.test(
      'update-ref-has-diff-has-change',
      api.step_data('update ref (3).git transaction.diff check.git ls-files',
                    retcode=0),
      api.step_data('update ref (3).git transaction.diff check.git diff',
                    retcode=1))
