# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with git."""

import contextlib
import types
from collections import namedtuple

from recipe_engine import recipe_api

Commit = namedtuple('Commit', ['rev', 'message'])


class GitApi(recipe_api.RecipeApi):
  """A module for interacting with git."""

  def _step(self, args, name=None, test_stdout=None, **kwargs):
    """Executes 'git' with the supplied arguments.

    Args:
      * args (list): A list of arguments to supply to 'git'.
      * name (str): The name of the step. If None, generate from the args.
      * test_stdout (str): Data to return as stdout when testing.
      * kwargs: See 'step.__call__'.

    Returns:
      StepData: See 'step.__call__'.
    """
    if name is None:
      name = 'git'
      # Add first non-flag argument to name.
      for arg in args:
        if isinstance(arg, types.StringTypes) and arg[:1] != '-':
          name += ' ' + arg
          break
    if test_stdout is not None:
      assert 'step_test_data' not in kwargs, 'test_stdout with step_test_data'
      kwargs['step_test_data'] = (
          lambda: self.m.raw_io.test_api.stream_output(test_stdout))

    kwargs.setdefault('infra_step', True)
    return self.m.step(name, ['git'] + args, **kwargs)

  def add(self, path):
    """Add/stage a path.

    Stages `path` for commit. Note that this will fail if the file is tracked
    and not modified, which you can use `diff_check` to check for.

    Args:
      * path (str|Path): The file path to stage.
    """
    self._step(['add', path])

  def diff_check(self, path):
    """Check if the given file changed from HEAD.

    Args:
      * path (str|Path): The file path to check for changes.

    Returns:
      bool: True if the file changed from HEAD (or didn't exists), False
          otherwise.
      """
    # Both `ls-files` and `diff-index` appear to be needed here. They return:
    #  git ls-files --error-unmatch <FILE>
    #    0 - no change & change
    #    1 - untracked new file
    #  git diff-index --quiet HEAD <FILE>
    #    0 - no change to existing file
    #    1 - change to existing file || staged new file
    #    128 - other (missing file)
    with self.m.step.nest('diff check'):
      if self._step(['ls-files', '--error-unmatch', path],
                    ok_ret=(0, 1)).retcode != 0:
        return True

      return self._step(['diff-index', '--quiet', 'HEAD', path],
                        ok_ret=(0, 1)).retcode != 0

  def get_diff_files(self, from_rev, to_rev):
    """Runs 'git diff' to find files changed between <from_rev> and <to_rev>.

    Args:
      * from_rev (str): Revision to start at. Can be a commit or ref (e.g.
        'HEAD', 'origin/master').
      * to_rev (str): Revision to end at.
    Returns:
      A list[str] of changed files.
    """
    test_stdout = """
a/b/text.txt
other_test.txt
"""
    step_data = self._step(
        ['diff', '--name-only', '{}...{}'.format(from_rev, to_rev)],
        stdout=self.m.raw_io.output(), test_stdout=test_stdout)
    return step_data.stdout.strip().split('\n')

  def fetch(self, remote, refspecs=None):
    """Runs 'git fetch'.

    Args:
      * remote (str): The remote repository to fetch from.
      * refspecs (list[str]): The refspecs to fetch.
    """
    args = ['fetch', remote]
    if refspecs is not None:
      args += refspecs
    self._step(args)

  def fetch_ref(self, remote, ref):
    """Fetch a single remote ref with 'git fetch'.

    Args:
      * remote (str): The remote repository to fetch from.
      * ref (str): The ref to fetch.

    Returns:
      str: The commit ID of the fetched ref.
    """
    self.fetch(remote, ['%s:' % ref])

    step_data = self._step(['rev-parse', 'FETCH_HEAD'],
                           stdout=self.m.raw_io.output(),
                           test_stdout='%s\n' % self.test_api.test_commit_id)
    return step_data.stdout.strip()

  def checkout(self, commit, force=False):
    """Runs 'git checkout'.

    Args:
      * commit (str): The commit (technically "tree-like") to checkout.
      * force (bool): If True, throw away local changes (--force).
    """
    args = ['checkout']
    if force:
      args += ['--force']
    args += [commit]
    self._step(args)

  def cherry_pick(self, commit):
    """Runs 'git cherry-pick'.

    Args:
      * commit (str): The commit to cherry pick.
    """
    self._step(['cherry-pick', commit])

  def commit_files(self, files, message):
    """Runs 'git commit' with the given files.

    Args:
      * files (list[str|Path]): A list of file paths to commit.
      * message (str): The commit message.
    """
    self._step(['commit', '--message', message, '--'] + files)

  def push(self, remote, refspec, capture_stdout=False):
    """Runs 'git push'.

    Args:
      remote (str): The remote repository to push to.
      refspec (str): The refspec to push.
      capture_stdout (bool): If True, return stdout in step data.

    Returns:
      StepData: See 'step.__call__'.
    """
    args = ['push']
    stdout = None
    if capture_stdout:
      args += ['--porcelain']
      stdout = self.m.raw_io.output(add_output_log=True)
    args += [remote, refspec]
    return self._step(args, stdout=stdout)

  def current_branch(self):
    """Returns the currently checked out branch name.

    Returns:
      str: The branch name pointed to by HEAD.
      None: If HEAD is detached.
    """
    step_data = self._step(['symbolic-ref', '--short', 'HEAD'],
                           ok_ret=(0, 1, 128), stdout=self.m.raw_io.output(),
                           test_stdout='master\n')
    if step_data.retcode != 0:
      return None
    return step_data.stdout.strip()

  def head_commit(self):
    """Returns the HEAD commit ID."""
    return self._step(
        ['rev-parse', 'HEAD'], stdout=self.m.raw_io.output(),
        test_stdout='%s\n' % self.test_api.test_commit_id).stdout.strip()

  @contextlib.contextmanager
  def head_context(self):
    """Returns a context that will revert HEAD when it exits."""
    # Try to return to a current branch, but fallback to detached commit ID.
    head = self.current_branch() or self.head_commit()
    try:
      yield
    finally:
      self.checkout(head)

  def log(self, from_rev, to_rev):
    """Returns all the `Commit` between `from_rev` and `to_rev`.

    Args:
      from_rev (str): From revision
      to_rev (str): To revision

    Returns:
      List(Commit) A list of commit metas.
    """
    step_data = self._step(
        ['log', '--pretty=%H%x1E%B%x00',
         '%s...%s' % (from_rev, to_rev)], stdout=self.m.raw_io.output(),
        test_stdout='%s\x1Emessage\x00' % self.test_api.test_commit_id)
    stdout = step_data.stdout.strip().rstrip('\x00')
    commits = []
    for record in stdout.split('\x00'):
      ref, message = record.split('\x1E')
      commits.append(Commit(ref, message))
    return commits

  def is_reachable(self, revision):
    """Check if the given revision is reachable from HEAD.

    Args:
      revision (str): A git revision to search for.

    Returns:
      bool: True if the revision can be reached from HEAD.
    """
    cmd = ['merge-base', '--is-ancestor', revision, 'HEAD']
    return self._step(cmd, ok_ret=(0, 128)).retcode == 0

  def show_file(self, rev, path, test_contents=None):
    """Returns the contents of the given file path at the given revision.

    Args:
      rev (str): The revision to return the contents from.
      path (str): The file path to return the contents of.

    Returns:
      str: The contents of the file.
      None: The file does not exist at the given revision.
    """
    step_data = self._step(['show', '%s:%s' % (rev, path)], ok_ret=(0, 128),
                           stdout=self.m.raw_io.output(),
                           test_stdout=test_contents)
    if step_data.retcode != 0:
      return None
    return step_data.stdout

  def create_bundle(self, output_path, from_commit, to_ref):
    """Creates a git bundle file.

    Creates a git bundle (see `man git-bundle`) containing the commits from
    |from_commit| (exclusive) to |to_ref| (inclusive).

    Args:
      output_path (Path): Path to create bundle file at.
      from_commit (str): Parent commit (exclusive) for bundle.
      to_ref (str): Reference to put in bundle.
    """
    revs = '%s..%s' % (from_commit, to_ref)
    self._step(['bundle', 'create', output_path, revs])

  def position_num(self, ref='HEAD'):
    """Returns the chrome commit position.

    The ref must be present in the local checkout, and it must contain the
    Cr-Commit-Position footer or this function will fail.

    Args:
      ref (str): The ref to fetch to get the position num of.

    Returns:
      int: The Chrome commit position
    """
    result = self.m.python(
        'git_footers.py', self.m.depot_tools.root.join('git_footers.py'),
        args=[ref, '--position-num'], stdout=self.m.raw_io.output(),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output('101'),
        ok_ret='any')
    assert result.retcode == 0, 'malformed commit footers for %s' % ref
    return int(result.stdout.strip())

  def clone(self, repo_url, target_path=None):
    """Clones a Git repo into the current directory.

    Args:
      * repo_url (str): The URL of the repo to clone.
      * target_path (Path): Path in which to clone the repo, or None to specify
          current directory.
    """
    if target_path is None:
      # Clone into current directory (no extra subdirectory) by default.
      target_path = '.'
    self._step(['clone', repo_url, target_path])
