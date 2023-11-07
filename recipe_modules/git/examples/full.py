# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

# TODO(crbug/1098567): Refactor this to be actual examples, and move the tests
# into tests/.


def RunSteps(api):
  commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
  remote = 'https://mygithost.google.com/somerepo'
  api.git.clone(remote)
  api.git.clone(remote, reference=api.path.mkdtemp(), dissociate=True)
  api.git.clone(remote, branch='release')
  api.git.clone(remote, single_branch=True)
  api.git.clone(remote, verbose=True, progress=True)
  api.git.clone(remote, depth=1)
  api.git.create_branch('branch', 'cros/branch')
  api.git.fetch('remote')
  api.assertions.assertEqual(
      api.git.fetch_ref('remote', 'refs/heads/branch'), commit_id)
  api.git.remote_update('sync branches')
  api.git.checkout('main', force=True)
  api.assertions.assertEqual(api.git.remote_head(remote), 'refs/heads/main')
  api.assertions.assertEqual(api.git.remote_head(remote, test_stdout=''), None)
  api.git.merge('branch', 'yeet')
  api.git.merge_abort()
  api.git.cherry_pick('branch')
  api.git.commit('Updated README\n\nMuch better now.', files=['README.md'],
                 author='John Doe <john.doe@example.com>')
  api.git.amend_head_message('Updating README\n\nMuch better now.')
  api.git.stash()

  api.assertions.assertEqual(api.git.remote_url(),
                             'https://chromium.googlesource.com')
  api.git.push('origin', 'HEAD:main', dry_run=True, capture_stdout=True,
               capture_stderr=True, force=True, infra_step=False, timeout=30)

  with api.step.nest('check diffs') as presentation:
    has_diffs = api.git.diff_check('some/file/path')
    presentation.text = has_diffs

  commits = api.git.log('START_REF', 'END_REF', limit=30, paths=['file*'])
  if commits:
    [commit] = commits
    api.assertions.assertEqual(commit.rev, commit_id)
    api.assertions.assertEqual(commit.message, 'message')
    api.git.add(['some/file/path', 'some/other/path'])
    api.git.is_reachable('deadbeef')
    api.git.show_file('deadbeef', 'some/path')
    api.git.create_bundle(api.path['start_dir'].join('bundle'), 'HEAD^', 'HEAD')
    api.assertions.assertEqual(
        api.git.get_diff_files('main', 'HEAD'),
        ['a/b/text.txt', 'other_test.txt'])
    api.assertions.assertEqual(
        api.git.get_diff_files('main'), ['a/b/text.txt', 'other_test.txt'])
    api.assertions.assertEqual(api.git.get_diff_files(),
                               ['a/b/text.txt', 'other_test.txt'])
    api.assertions.assertFalse(api.git.get_diff_files(test_stdout='\n'), [])
    api.assertions.assertEqual(api.git.get_working_dir_diff_files(),
                               ['changed.txt', 'new.txt'])
    api.assertions.assertIsNone(api.git.merge_base('commit1', 'commit2'))
    api.assertions.assertEqual(
        api.git.merge_base('commit1', 'commit2', test_stdout='commit3'),
        'commit3')

  with api.git.head_context():
    pass

  api.assertions.assertEqual(len(api.git.ls_remote(['snapshot', 'foo'])), 2)
  api.git.repository_root()
  api.git.rebase(force=True)
  api.git.rebase(force=True, branch='feature-branch')
  api.git.rebase(strategy_option='strategy-option')
  api.git.set_global_config(['upstream.hammer-branch', '1'])

  commit = api.git.gitiles_commit(test_url='https://example.com/pro/ject/')
  api.assertions.assertEqual('example.com', commit.host)
  api.assertions.assertEqual('pro/ject', commit.project)
  api.assertions.assertEqual(api.src_state.default_ref, commit.ref)

  api.assertions.assertEqual(
      api.git.extract_branch('refs/heads/something', 'whatever'), 'something')
  api.assertions.assertEqual(api.git.extract_branch('something'), 'something')
  api.assertions.assertEqual(
      api.git.extract_branch('refs/tags/something', 'whatever'), 'whatever')
  api.assertions.assertEqual(
      api.git.get_branch_ref('something'), 'refs/heads/something')
  api.assertions.assertEqual(
      api.git.get_branch_ref('refs/heads/something'), 'refs/heads/something')

  api.assertions.assertEqual(api.git.is_merge_commit(commit_id), False)

  api.assertions.assertEqual(api.git.author_email('HEAD'), 'foo@example.com')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'diff-check',
      api.git.diff_check(True),
  )

  yield api.test(
      'is-reachable',
      api.git.is_reachable(False),
  )

  yield api.test(
      'log-yields-no-output',
      api.step_data('git log', stdout=api.raw_io.output('')),
  )

  yield api.test(
      'show-file-path-not-found',
      api.step_data('git show', retcode=128),
  )

  yield api.test(
      'detached-HEAD',
      api.step_data('git symbolic-ref', retcode=1),
  )

  yield api.test(
      'diff-check-has-new-file',
      api.step_data('check diffs.diff check.git ls-files', retcode=1),
  )

  yield api.test(
      'is-merge-commit-fails',
      api.step_data('git log (2)', retcode=1),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'merge-base-fails',
      api.step_data('git merge-base (2)', retcode=1),
  )
