# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with git."""

from collections import namedtuple
import contextlib
from datetime import timedelta
from urllib.parse import urlparse

from typing import Optional

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry


Commit = namedtuple('Commit', ['rev', 'message'])
Reference = namedtuple('Reference', ['hash', 'ref'])


class GitApi(recipe_api.RecipeApi):
  """A module for interacting with git."""

  Commit = Commit
  Reference = Reference

  def _step(self, args, name=None, test_stdout=None, log_args=False, **kwargs):
    """Executes 'git' with the supplied arguments.

    Args:
      args (list): A list of arguments to supply to 'git'.
      name (str): The name of the step. If None, generate from the args.
      test_stdout (str): Data to return as stdout when testing.
      kwargs: See 'step.__call__'.

    Returns:
      (StepData): See 'step.__call__'.
    """
    if name is None:
      name = 'git'
      # Add first non-flag argument to name.
      for arg in args:
        if isinstance(arg, str) and arg[:1] != '-':
          name += ' ' + arg
          break
    if test_stdout is not None:
      assert 'step_test_data' not in kwargs, 'test_stdout with step_test_data'
      kwargs['step_test_data'] = (
          lambda: self.m.raw_io.test_api.stream_output_text(test_stdout))

    kwargs.setdefault('infra_step', True)
    if log_args:
      with self.m.step.nest('log command'):
        self.m.step.active_result.presentation.step_text = 'running git with args: %s' % [
            str(i) for i in args
        ]
    return self.m.step(name, ['git'] + args, **kwargs)

  def repository_root(self, step_name=None):
    """Return the git repository root for the current directory.

    Args:
      step_name (str): the step name to use instead of the default.

    Returns:
      (str): The path to the git repository.
    """
    return self._step(
        ['rev-parse', '--show-toplevel'],
        stdout=self.m.raw_io.output_text(),
        test_stdout=str(self.m.context.cwd),
        name=step_name,
    ).stdout.strip()

  def add(self, paths):
    """Add/stage paths.

    Stages `paths` for commit. Note that this will fail if a file is tracked
    and not modified, which you can use `diff_check` to check for.

    Args:
      paths (list[str|Path]): The file paths to stage.
    """
    self._step(['add'] + paths)

  def add_all(self):
    """Add/stage all changed files."""
    self._step(['add', '-A'])

  def diff_check(self, path):
    """Check if the given file changed from HEAD.

    Args:
      path (str|Path): The file path to check for changes.

    Returns:
      (bool): True if the file changed from HEAD (or doesn't exist), False
          otherwise.
    """
    # Both `ls-files` and `diff-index` appear to be needed here. They return:
    #  git ls-files --error-unmatch <FILE>
    #    0 - no change & change
    #    1 - untracked new file
    #  git diff --quiet HEAD <FILE>
    #    0 - no change to existing file
    #    1 - change to existing file || staged new file
    #    128 - other (missing file)
    with self.m.step.nest('diff check'):
      if self._test_data.enabled:
        has_diffs = self._test_data.get('diff_check', None)
        if has_diffs is not None:
          return has_diffs

      if self._step(['ls-files', '--error-unmatch', path],
                    ok_ret=(0, 1)).retcode != 0:
        return True

      return self._step(['diff', '--quiet', 'HEAD', path],
                        ok_ret=(0, 1)).retcode != 0

  def get_diff_files(self, from_rev=None, to_rev=None, test_stdout=None):
    """Runs 'git diff' to find files changed between two revs.

    Revs are passed directly to 'git diff', which has the following effect:
      0 revs - Changes between working directory and index
      1 revs - Changes between working directory and given commit
      2 revs - Changes between the two commits

    Note that this does not include new/untracked files.

    Args:
      from_rev (str): First revision  (see 'man 7 gitrevisions')
      to_rev (str): Second revision

    Returns:
      (list[str]): changed files.
    """

    if not test_stdout:
      test_stdout = '\n'.join(['a/b/text.txt', 'other_test.txt'])

    cmd = ['diff', '--name-only']
    cmd += [from_rev] if from_rev else []
    cmd += [to_rev] if to_rev else []

    step_data = self._step(cmd, stdout=self.m.raw_io.output_text(),
                           test_stdout=test_stdout)

    output = step_data.stdout.strip()
    if not output:
      return []
    return output.split('\n')

  def get_working_dir_diff_files(self):
    """Finds all changed files (including untracked)."""
    test_stdout = '''
 M changed.txt
?? new.txt
'''
    step_data = self._step(['status', '--porcelain'],
                           stdout=self.m.raw_io.output_text(),
                           test_stdout=test_stdout)

    # Need to strip the diff mode characters, e.g. "?? "
    return [line[2:].strip() for line in step_data.stdout.strip().splitlines()]

  def _fetch(self, remote: Optional[str], refspecs, timeout_sec):
    """Runs 'git fetch'.

    Args:
      remote (str): The remote repository to fetch from. Optional!
      refspecs (list[str]): The refspecs to fetch.
      timeout_sec (int): Timeout in seconds.
    """
    args = ['fetch']
    if remote is not None:
      args.append(remote)
    if refspecs is not None:
      args += refspecs
    self._step(args, timeout=timeout_sec)

  def fetch(self, remote=None, refs=None, timeout_sec=None, retries=2):
    """Runs 'git fetch'.

    Args:
      remote (str): The remote repository to fetch from.
      refs (list[str]): The refs to fetch.
      timeout_sec (int): Timeout in seconds.
      retries (int): Number of times to retry.
    """
    func = self._fetch
    if retries:
      delay = timedelta(seconds=1)
      func = self.m.time.exponential_retry(retries=retries, delay=delay)(func)
    return func(remote, refs, timeout_sec)

  def fetch_refs(self, remote, ref, timeout_sec=None, count=1, test_ids=None):
    """Fetch a list of remote refs.

    Args:
      remote (str): The remote repository to fetch from.
      ref (str): The ref to fetch.
      timeout_sec (int): Timeout in seconds.
      count (int): The number of commit IDs to return.
      test_ids (list[str]): List of test commit IDs, or None.

    Returns:
      (list[str]): The commit IDs, starting with the fetched ref.
    """
    self.fetch(remote, ['%s:' % ref])
    test_ids = test_ids or self.test_api.generate_test_ids(count)
    test_retcode = 0 if len(test_ids) == count else 1

    # Normally, there will be |count| elements in the output.  If the repo is
    # too new, then this command will fail, and we will loop.
    step_data = self._step(
        ['log', 'FETCH_HEAD~%d..FETCH_HEAD' % count, '--pretty=%H'],
        stdout=self.m.raw_io.output_text(), timeout=timeout_sec,
        step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
            '\n'.join(test_ids) + '\n', retcode=test_retcode), ok_ret=(0, 1))
    if step_data.retcode == 0:
      return step_data.stdout.splitlines()

    ret = []
    for idx in range(count):
      step_data = self._step(['rev-parse', 'FETCH_HEAD~%d' % idx],
                             stdout=self.m.raw_io.output_text(),
                             timeout=timeout_sec,
                             test_stdout='%s\n' % test_ids[idx], ok_ret=(0, 1))
      if step_data.retcode:
        break
      ret.append(step_data.stdout.strip())

    return ret

  def fetch_ref(self, remote, ref, timeout_sec=None):
    """Fetch a ref, and return the commit ID (SHA).

    Args:
      remote (str): The remote repository to fetch from.
      ref (str): The ref to fetch.
      timeout_sec (int): Timeout in seconds.

    Returns:
      (str): The commit ID (SHA) of the fetched ref.
    """
    self.fetch(remote, ['%s:' % ref])

    step_data = self._step(['rev-parse', 'FETCH_HEAD'],
                           stdout=self.m.raw_io.output_text(),
                           timeout=timeout_sec,
                           test_stdout='%s\n' % self.test_api.test_commit_id)
    return step_data.stdout.strip()

  @exponential_retry(retries=19, delay=timedelta(minutes=1))
  def remote_update(self, step_name, timeout_sec=None):
    """Runs 'git remote update'.

    Args:
      step_name (str): Name of the step to display.
      timeout_sec (int): Timeout in seconds.
    """
    self._step(['remote', 'update'], name=step_name, timeout=timeout_sec)

  def checkout(self, commit=None, force=False, branch=None, **kwargs):
    """Runs 'git checkout'.

    Args:
      commit (Optional[str]): The commit (technically "tree-like") to checkout.
      force (bool): If True, throw away local changes (--force).
      branch (Optional[str]): The branch to check out a commit from.
    """
    args = ['checkout']
    if force:
      args += ['--force']
    if branch:
      args += ['-b', branch]
    if commit:
      args += [commit]
    self._step(args, **kwargs)

  def merge(self, ref, message, *args, **kwargs):
    """Runs `git merge`.

    Args:
      ref (str): The ref to merge.
      message (str): The merge commit message.
      args (tuple): Additional arguments to git merge.
      kwargs (dict): Passed to recipe_engine/step.
    """
    kwargs.setdefault('stdout', self.m.raw_io.output_text())
    self._step(['merge', ref, '-m', message] + list(args), **kwargs)

  def cherry_pick(self, commit, **kwargs):
    """Runs 'git cherry-pick'.

    Args:
      commit (str): The commit to cherry pick.
      kwargs (dict): Passed to recipe_engine/step.
    """
    kwargs.setdefault('stdout', self.m.raw_io.output_text())
    self._step(['cherry-pick', commit], **kwargs)

  def cherry_pick_silent_fail(self, commit, **kwargs):
    """Runs 'git cherry-pick' and returns whether the cherry-pick succeeded.

    Args:
      commit (str): The commit to cherry pick.
      kwargs (dict): Passed to recipe_engine/step.
    """
    kwargs.setdefault('stdout', self.m.raw_io.output_text())
    success = self._step(['cherry-pick', commit], ok_ret=(0, 1),
                         **kwargs).retcode == 0
    return success

  def merge_abort(self):
    """Runs 'git merge --abort'."""
    self._step(['merge', '--abort'], name='git merge --abort')

  def cherry_pick_abort(self):
    """Runs 'git cherry_pick --abort'."""
    self._step(['cherry-pick', '--abort'], name='git cherry-pick --abort')

  def amend_head_message(self, message, **kwargs):
    """Runs 'git commit --amend' with the given description.

    Args:
      message (str): The commit message.
      kwargs (dict): Passed to recipe_engine/step.
    """
    kwargs.setdefault('stdout', self.m.raw_io.output_text())
    # Single argument can't exceed 128kiB (crbug/987630), write to temp
    # and pass the argument as a file
    commit_msg_path = self.m.path.mkstemp(prefix='commit_msg')
    str_message = message.encode('utf-8')
    self.m.file.write_text('write commit message', commit_msg_path, str_message)

    cmd = ['commit', '--amend', '--file', str(commit_msg_path)]
    return self._step(cmd, **kwargs)

  def commit(self, message, files=None, author=None, **kwargs):
    """Runs 'git commit' with the given files.

    Args:
      message (str): The commit message.
      files (list[str|Path]): A list of file paths to commit.
      author (str): The author to use in the commit. Ordinarily not used,
        added to test permission oddities by forcing forged commit failure.
      kwargs (dict): Passed to recipe_engine/step.
    """
    # Single argument can't exceed 128kiB (crbug/987630), write to temp
    # and pass the argument as a file
    commit_msg_path = self.m.path.mkstemp(prefix='commit_msg')
    str_message = message.encode('utf-8')
    self.m.file.write_text('write commit message', commit_msg_path, str_message)

    cmd = ['commit', '--file', str(commit_msg_path)]
    if author:
      cmd.extend(['--author', author])
    if files:
      cmd.append('--')
      cmd.extend(files)
    return self._step(cmd, **kwargs)

  def _push(self, remote, refspec, dry_run, capture_stdout, capture_stderr,
            force, **kwargs):
    """Runs 'git push'.

    Args:
      remote (str): The remote repository to push to.
      refspec (str): The refspec to push.
      dry_run (bool): If true, set --dry-run on git command.
      capture_stdout (bool): If True, return stdout in step data.
      capture_stderr (bool): If True, return stderr in step data.
      force (bool): add force flag for git push
      kwargs (dict): Passed to api.step.

    Returns:
      (StepData): See 'step.__call__'.
    """
    args = ['push']
    if dry_run:
      args += ['--dry-run']
    if force:
      args += ['--force']
    stdout = None
    stderr = None
    if capture_stdout or capture_stderr:
      args += ['--porcelain']
    if capture_stdout:
      stdout = self.m.raw_io.output_text(add_output_log=True)
    if capture_stderr:
      stderr = self.m.raw_io.output_text(add_output_log=True)
    args += [remote, refspec]
    return self._step(args, stdout=stdout, stderr=stderr, **kwargs)

  def push(self, remote, refspec, dry_run=False, capture_stdout=False,
           capture_stderr=False, retry=True, force=False, **kwargs):
    """Runs 'git push'.

    Args:
      remote (str): The remote repository to push to.
      refspec (str): The refspec to push.
      dry_run (bool): If true, set --dry-run on git command.
      capture_stdout (bool): If True, return stdout in step data.
      capture_stderr (bool): If True, return stderr in step data.
      retry (bool): Whether to retry.  Default: True
      force (bool): add force flag for git push
      kwargs (dict): Passed to api.step.

    Returns:
      (StepData): See 'step.__call__'.
    """
    func = self._push
    if retry:
      func = self.m.time.exponential_retry(retries=2,
                                           delay=timedelta(seconds=2))(
                                               self._push)
    return func(remote, refspec, dry_run, capture_stdout, capture_stderr, force,
                **kwargs)

  def current_branch(self):
    """Returns the currently checked out branch name.

    Returns:
      (str): The branch name pointed to by HEAD.
      None: If HEAD is detached.
    """
    step_data = self._step(
        ['symbolic-ref', '--short', 'HEAD'], ok_ret=(0, 1, 128),
        stdout=self.m.raw_io.output_text(),
        test_stdout='{}\n'.format(self.m.src_state.default_branch))
    if step_data.retcode != 0:
      return None
    ret = step_data.stdout.strip()
    self.m.step.active_result.presentation.logs['branch'] = ret
    return ret

  def remote_head(self, remote='.', test_stdout=None):
    """Returns the HEAD ref of the given remote.

    Args:
       remote (str): remote name to query, by default remote of current branch

    Returns:
       (str): ref contained in the remote HEAD (ie the default branch), or None
          on error.
    """
    if test_stdout is None:
      test_stdout = 'ref: refs/heads/main  HEAD\n'

    step_data = self._step(
        ['ls-remote', '--symref', remote, 'HEAD'],
        ok_ret=(0, 1),
        stdout=self.m.raw_io.output_text(),
        test_stdout=test_stdout,
    )

    for line in step_data.stdout.split('\n'):
      if line.startswith('ref:'):
        _, ref, _ = line.split()
        return ref
    return None

  def head_commit(self):
    """Returns the HEAD commit ID."""
    ret = self._step(['rev-parse', 'HEAD'], stdout=self.m.raw_io.output_text(),
                     test_stdout='%s\n' %
                     self.test_api.test_commit_id).stdout.strip()
    self.m.step.active_result.presentation.logs['HEAD'] = ret
    return ret

  @contextlib.contextmanager
  def head_context(self):
    """Returns a context that will revert HEAD when it exits."""
    # Try to return to a current branch, but fallback to detached commit ID.
    head = self.current_branch() or self.head_commit()
    try:
      yield
    finally:
      self.checkout(head)

  def ls_remote(self, refs, repo_url=None):
    """Return ls-remote output for a repository.

    Args:
      refs (list[str]): The refs to list.
      repo_url (str): The url of the remote, or None to use CWD.

    Returns:
      (list[Reference]): A list of Refs.
    """
    cmd = ['ls-remote', repo_url or '.'] + refs
    test_stdout = '\n'.join(
        '%s\t%s' % (self.test_api.test_commit_id, x) for x in refs)
    stdout = self._step(cmd, stdout=self.m.raw_io.output_text(),
                        test_stdout=test_stdout).stdout.strip()
    refs = []
    for line in stdout.splitlines():
      commit, ref = line.split()
      refs.append(self.Reference(commit, ref))
    return refs

  def log(self, from_rev, to_rev, limit=None, paths=None):
    """Returns all the `Commit` between `from_rev` and `to_rev`.

    Args:
      from_rev (str): From revision
      to_rev (str): To revision
      limit (int): Maximum number of commits to log.
      paths (list[str]): pathspecs to use.

    Returns:
      (list[Commit]): A list of commit metas.
    """
    cmd = ['log', '--pretty=%H%x1F%B%x00', '%s...%s' % (from_rev, to_rev)]
    if limit is not None:
      cmd.append('-%d' % limit)
    if paths:
      cmd.append('--')
      cmd.extend(paths)
    step_data = self._step(
        cmd, stdout=self.m.raw_io.output_text(),
        test_stdout='%s\x1Fmessage\x00' % self.test_api.test_commit_id)
    stdout = step_data.stdout.strip().rstrip('\x00')
    self.m.step.active_result.presentation.logs['stdout'] = step_data.stdout

    commits = []
    if stdout:
      # We need to check for an empty stdout, because ''.split('\x00')
      # returns [''].
      for record in stdout.split('\x00'):
        ref, message = record.split('\x1F')
        commits.append(self.Commit(ref.strip('\n'), message))
    return commits

  def is_reachable(self, revision, head='HEAD'):
    """Check if the given revision is reachable from HEAD.

    Args:
      revision (str): A git revision to search for.
      head (str): The starting revision.  Default: HEAD.

    Returns:
      (bool): Whether the revision is reachable from (is an ancestor of) |head|.
    """
    # Short circuit identical refs.
    if revision == head:
      return True

    test_retcode = None
    if self._test_data.enabled:
      test_is_reachable = self._test_data.get('is_reachable', None)
      if test_is_reachable is not None:
        test_retcode = 0 if test_is_reachable else 1

    cmd = ['merge-base', '--is-ancestor', revision, head]
    try:
      retcode = test_retcode or self._step(cmd, ok_ret=(0, 1),
                                           log_args=True).retcode
      self.m.step.active_result.presentation.step_text = (
          'commit is %sreachable' % ('NOT ' if retcode == 1 else ''))
      return not retcode
    except recipe_api.StepFailure:
      self.m.step.active_result.presentation.step_text = (
          'call failed with an exception')
      self.m.step.active_result.presentation.status = self.m.step.WARNING
      return False

  def merge_base(self, *args, **kwargs):
    """Return the output from `git merge-base`.

    Args:
      args (tuple): Additional arguments to git merge.
      kwargs (dict): Passed to recipe_engine/step.

    Returns:
      (str) stdout of the command, or None for errors.
    """
    kwargs.setdefault('ok_ret', (0, 1, 128))
    kwargs.setdefault('stdout', self.m.raw_io.output_text())
    step_data = self._step(['merge-base'] + list(args), **kwargs)
    if step_data.retcode != 0:
      return None
    return step_data.stdout.strip() or None

  def show_file(self, rev, path, test_contents=None):
    """Returns the contents of the given file path at the given revision.

    Args:
      rev (str): The revision to return the contents from.
      path (str): The file path to return the contents of.

    Returns:
      (str): The contents of the file, None if the file does not exist in |rev|.
    """
    step_data = self._step(['show', '%s:%s' % (rev, path)], ok_ret=(0, 128),
                           stdout=self.m.raw_io.output_text(),
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

  def clone(self, repo_url, target_path=None, reference=None, dissociate=False,
            branch=None, single_branch=False, depth=None, timeout_sec=None,
            verbose=False, progress=False):
    """Clones a Git repo into the current directory.

    Args:
      repo_url (str): The URL of the repo to clone.
      target_path (Path): Path in which to clone the repo, or None to specify
        current directory.
      reference (Path): Path to the reference repo.
      dissociate (bool): Whether to dissociate from reference.
      branch (string): If set, performs a single branch clone of that branch.
      single_branch (bool): If set, performs a single branch clone of the
         default branch.
      depth (int): If set, creates a shallow clone at the specified depth.
      timeout_sec (int): Timeout in seconds.
      verbose (bool): If set, run git clone as verbose.
      progress (bool): If set, print progress to stdout.
    """
    if target_path is None:
      # Clone into current directory (no extra subdirectory) by default.
      target_path = '.'
    args = ['clone']
    if reference:
      args += ['--reference', reference]
    if dissociate:
      args += ['--dissociate']
    if branch:
      args += ['--branch', branch, '--single-branch']
    elif single_branch:
      args += ['--single-branch']
    if depth is not None:
      args += ['--depth', depth]
    args += [repo_url, target_path]
    if verbose:
      args += ['-v']
    if progress:
      args += ['--progress']
    self._step(args, timeout=timeout_sec)

  def rebase(self, force=False, branch=None, strategy_option=None):
    """Run `git rebase` with the given arguments.

    Args:
      force (bool): If True, set --force.
      branch (str): If set, rebase from specific branch.
      strategy_option (str): If set, sets the --strategy-option flag. See
        `git help rebase` for details.
    """
    cmd = ['rebase']
    if force:
      cmd.append('--force-rebase')
    if branch:
      cmd.append(branch)
    if strategy_option:
      cmd.extend(['--strategy-option', strategy_option])
    self._step(cmd)

  def set_global_config(self, args):
    """Runs `git config --global` to set global config.

    Args:
      args (list[str]): args for `git config`.
    """
    self._step(['config', '--global'] + args)

  def extract_branch(self, refspec, default=None):
    """Splits the branch from the refspec.

    Splits the branch from a refs/heads refspec and returns it. Returns
    default if the refspec is not of the required format.

    Args:
      refspec (str): refspec to split the branch from.
      default (str): value to return if refspec not of required format.

    Returns:
      (str): the extracted branch name.
    """
    if refspec.startswith('refs/heads/'):
      return refspec.split('/', 2)[2]
    if not default:
      return refspec
    return default

  def get_branch_ref(self, branch):
    """Creates the full ref for a branch.

    Returns a ref of the form refs/heads/{branch}.

    Args:
      branch (str): branch to split the branch from.

    Returns:
      (str): The ref for the branch.
    """
    if branch.startswith('refs/heads/'):
      return branch
    return 'refs/heads/' + branch

  def get_parents(self, commit_id, test_contents=None):
    """Runs `get log` to determine the parents of a git commit.

    Args:
      commit_id (str): The commit hash.

    Returns:
      (list[str]): parent commit hash(es).
    """
    step_data = self._step(['log', '--pretty=%P', '-n 1', commit_id],
                           stdout=self.m.raw_io.output_text(),
                           test_stdout=test_contents)
    return step_data.stdout.split(' ')

  def is_merge_commit(self, commit_id):
    """Determines if the commit_id is a merge commit.

    Args:
      commit_id (str): The commit sha.

    Returns:
      (bool): whether the commit has more than 1 parent.
    """
    return len(self.get_parents(commit_id)) > 1

  def gitiles_commit(self, test_remote='cros-internal', test_url=None):
    """Return a GitilesCommit for HEAD.

    Args:
      test_remote (str): The name of the remote, for tests.
      test_url (str): Test data: url for the remote, for tests.

    Returns:
      (GitilesCommit): The GitilesCommit corresponding to HEAD.
    """
    remote = self._step(['remote'], stdout=self.m.raw_io.output_text(),
                        test_stdout=test_remote).stdout.splitlines()[0]
    test_url = (
        test_url or
        'https://chrome-internal.googlesource.com/chromeos/manifest-internal')
    url_parts = urlparse(
        self._step(['remote', 'get-url', remote],
                   stdout=self.m.raw_io.output_text(),
                   test_stdout=test_url).stdout.strip())
    commit_sha = self.head_commit()
    ref = 'refs/heads/{}'.format(self.current_branch())
    return GitilesCommit(host=url_parts.netloc, id=commit_sha, ref=ref,
                         project=url_parts.path.strip('/'))

  def remote_url(self, remote='origin'):
    """Get the URL for a defined remote.

    Args:
      remote (str): The name of the remote to query

    Returns:
      URL to the remote on success
    """
    result = self._step(
        ['remote', 'get-url', remote],
        stdout=self.m.raw_io.output_text(),
        test_stdout='https://chromium.googlesource.com',
    )
    return result.stdout.strip()

  def set_upstream(self, remote, branch):
    """ Set the upretrem for the given branch.

    Args:
      remote (str): The remote repository to track.
      branch (str): The remote branch to push to.

    Returns:
      (StepData): See 'step.__call__'.
    """
    result = self._step(
        ['branch', '--set-upstream-to=%s/%s' % (remote, branch)],
        stdout=self.m.raw_io.output_text())

    return result

  def author_email(self, commit_id):
    """Returns the email of the author of the given commit.

    Args:
      * commit_id (str): The commit sha.

    Returns: (str): commit author email.
    """
    return self._step(['log', '--format=%aE', '-n', '-1', commit_id],
                      stdout=self.m.raw_io.output_text(), test_stdout='%s\n' %
                      self.test_api.test_author_email).stdout.strip()

  def remote(self):
    """Return the name of the remote.

    Returns: (str): name of the remote, e.g. 'origin' or 'cros'.
    """
    result = self._step(['remote'], stdout=self.m.raw_io.output_text())

    remotes = result.stdout.strip().split('\n')
    if len(remotes) > 1:
      raise recipe_api.StepFailure(
          'more than one remote ({}), not sure which to return'.format(
              ','.join(remotes)))
    return remotes[0]

  def create_branch(self, branch, remote_branch=None):
    """Create a branch.

    Args:
      * branch (str): Name of the branch to be created, e.g. mybranch. This
        branch may not already exist.
      * remote_branch (str): Name of the remote branch to track, e.g.
        origin/main or cros/mybranch.
    """
    cmd = ['branch', branch]
    if remote_branch:
      cmd.append(remote_branch)
    self._step(cmd)

  def branch_exists(self, branch):
    """Check if a branch exists.

    Args:
      * branch (str): Name of the branch to check.

    Returns: (bool) Whether or not the branch exists.
    """
    result = self._step(['branch'], stdout=self.m.raw_io.output_text())
    branches = [b.lstrip('* ') for b in result.stdout.strip().split('\n')]
    return branch in branches

  def stash(self):
    """Stash changes."""
    self._step(['stash'])

  def delete_local_branch(self, branch):
    """Deletes the local branch (if it exists).
      Args:
        branch (str): Name of the branch to be deleted.
      """
    if not self.branch_exists(branch):
      return

    cmd = ['branch', '-D', branch]
    self._step(cmd, name='git branch -D ' + branch)
