# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/raw_io',
    'src_state',
    'git_txn',
]



def RunSteps(api):
  with api.context(cwd=api.src_state.workspace_path / 'src/project'):
    api.git_txn.update_ref('remote', lambda: None, ref='ref', automerge=True)
    api.git_txn.update_ref('remote', lambda: False, ref='ref', automerge=True)
    api.git_txn.update_ref_write_files('remote', 'Update file',
                                       [('file/path.txt', 'data')], ref='ref',
                                       automerge=True)


def GenTests(api):
  yield api.test(
      'basic',
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
  yield api.test(
      'fail-empty-push-response',
      api.step_data('update ref.gerrit transaction.git push',
                    stderr=api.raw_io.output_text((''))),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
  yield api.test(
      'fail-incorrect-git-response',
      api.step_data(
          'update ref.gerrit transaction.git push',
          stderr=api.raw_io.output_text(
              ('https://chromium-review.googlesource.com'))),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'update-ref-has-diff-has-change',
      api.step_data(
          'update ref.gerrit transaction.git push',
          stderr=api.raw_io.output_text(
              ('remote:   https://chromium-review.googlesource'
               '.com/c/chromiumos/infra/recipes/+/123 git_txn: test'))),
      api.step_data('update ref (3).gerrit transaction.diff check.git ls-files',
                    retcode=0),
      api.step_data('update ref (3).gerrit transaction.diff check.git diff',
                    retcode=1),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'update-ref-has-diff-has-no-change',
      api.step_data(
          'update ref.gerrit transaction.git push',
          stderr=api.raw_io.output_text(
              ('remote:   https://chromium-review.googlesource'
               '.com/c/chromiumos/infra/recipes/+/123 git_txn: test'))),
      api.step_data('update ref (3).gerrit transaction.diff check.git ls-files',
                    retcode=0),
      api.step_data('update ref (3).gerrit transaction.diff check.git diff',
                    retcode=0))
