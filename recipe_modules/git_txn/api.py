# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for updating remote git repositories transactionally."""

import re
from recipe_engine import recipe_api


class Error(recipe_api.StepFailure):
  """Base error for this module."""


class TooManyAttempts(Error):
  """The transaction could not be completed in the allowed number of retries."""

  def __init__(self):
    super(TooManyAttempts, self).__init__(self.__doc__)


class GitTxnApi(recipe_api.RecipeApi):
  """A module for executing git transactions."""

  def _get_change_url(self, push_stdout):
    """Retrieve the URL pointing to the gerrit change.

    Args:
      push_stdout(str): The stdout returned from git.push().

    Returns:
      string: The full URL to the gerrit change reported by git.push().

    Raises:
      Error(StepFailure): If the stdout is empty or does not contain a gerrit
        change URL, a StepFailure is raised.
    """
    if not push_stdout:
      raise Error('No git push stdout returned')

    # Get the change URL for the CL
    pattern = r'^remote:\s+(https:\/\/.+\.googlesource\.com\/\S*)'
    for line in push_stdout.splitlines():
      # Match regex
      match = re.search(pattern, line)
      if match:
        return match.group(1)

    raise Error('No gerrit url found in git push output')

  def _gerrit_transaction(self, remote, update_callback, ref, dry_run):
    """Perform the transaction using gerrit tools for submission.

    Args:
      remote (str): The remote repository to update.
      update_callback (callable): The callback function that will update the
          local repo's HEAD. The callback is passed no arguments. If the
          callback returns False the update will be cancelled but succeed.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.
      dry_run (bool): If set, pass --dry-run to git push.

    Returns:
      bool: True if the transaction succeeded, false if it explicitly aborts.
    """
    if not ref.startswith('refs/for/'):
      ref = 'refs/for/%s' % ref
    with self.m.step.nest('gerrit transaction') as presentation:
      if update_callback() is False:
        presentation.step_text = 'Transaction aborted without failure.'
        return False

      push_stdout = self.m.git.push(remote, ref, capture_stdout=True,
                                    retry=False, dry_run=dry_run).stdout
      if not dry_run:
        # Push local changes up to git and capture the stdout.
        # Retrieve GerritChange from the stdout
        change_url = self._get_change_url(push_stdout)
        change = self.m.gerrit.parse_gerrit_change(change_url)
        label = {self.m.gerrit.Label.BOT_COMMIT: 1}
        self.m.gerrit.set_change_labels(change, label, ref=ref)
        self.m.gerrit.submit_change(change, retries=3)
      return True

  def _git_transaction(self, remote, update_callback, ref, dry_run, retries):
    """Perform the transaction using git tools only.

    Args:
      remote (str): The remote repository to update.
      update_callback (callable): The callback function that will update the
          local repo's HEAD. The callback is passed no arguments. If the
          callback returns False the update will be cancelled but succeed.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.
      dry_run (bool): If set, pass --dry-run to git push.
      retries (int): Number of update attempts, after the initial attempt,
          to make before failing.

    Returns:
      bool: True if the transaction succeeded, false if it explicitly aborts.

    Raises:
        TooManyAttempts: if the number of attempts exceeds |retries|."""
    step_name = 'git transaction'
    for i in range(retries + 1):
      if i > 0:
        step_name += ' attempt %d of %d' % (i, retries + 1)
      with self.m.step.nest(step_name) as presentation:
        if update_callback() is False:
          presentation.step_text = 'Transaction aborted without failure.'
          return False

        try:
          dest_ref = 'HEAD:%s' % ref
          self.m.git.push(remote, dest_ref, capture_stdout=True, retry=False,
                          dry_run=dry_run)
          return True
        except recipe_api.StepFailure as ex:
          # TODO(b/180405278): React to the error message in a more accurate way. see
          #   _check_push_exception() in annealing for reference.
          # Only retry on remote 'rejected' errors.
          if ex.retcode == 1 and 'rejected' in ex.result.stdout:
            ex.result.presentation.status = 'SUCCESS'

            self.m.git.fetch_ref(remote, ref)
            self.m.git.checkout('FETCH_HEAD', force=True)
          else:
            raise
    raise TooManyAttempts()

  def update_ref(self, remote, update_callback, step_name='update ref',
                 ref=None, dry_run=False, automerge=False, retries=3):
    """Transactionally update a remote git repository ref.

    |update_callback| will be called and should update the checked out HEAD by
    e.g. committing a new change. Then this new HEAD will be pushed back to the
    |remote| |ref|. If this push fails because the remote ref was modified in
    the meantime, and automerge is off, the new ref is fetched and checked out,
    and the process will repeat up to |retries| times.

    The common case is that there's no issue updating the ref, so we don't do
    a fetch and checkout before attempting to update.  This means that
    the function assumes that the repo is already checked out to the target
    ref.

    This step expects to be run with `cwd` inside a git repo.

    Args:
      remote (str): The remote repository to update.
      update_callback (callable): The callback function that will update the
          local repo's HEAD. The callback is passed no arguments. If the
          callback returns False the update will be cancelled but succeed.
      step_name (str): Step name to be displayed in the logs.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.
      dry_run (bool): If set, pass --dry-run to git push.
      automerge (bool): Whether to use Gerrit's "auto-merge" feature.
      retries (int): Number of update attempts to make before failing.

    Returns:
      bool: True if the transaction succeeded, false if it explicitly aborts.
    """
    ref = ref or self.m.git.remote_head(self.m.repo.project_info().remote)
    if not ref.startswith('refs/'):
      ref = 'refs/heads/%s' % ref
    with self.m.step.nest(step_name):
      if automerge:
        return self._gerrit_transaction(remote, update_callback, ref, dry_run)

      return self._git_transaction(remote, update_callback, ref, dry_run,
                                   retries)

  def update_ref_write_file(self, remote, message, dest, data, automerge=False,
                            ref=None):
    """Transactionally update a file in a remote git repository ref.

    See 'self.update_ref'. Instead of running a callback, this will attempt to
    update the contents of a file.

    Args:
      remote (str): The remote repository to update.
      message (str): The commit message to use.
      dest (Path): The path of the file to write.
      data (str): The data to write.
      automerge (bool): Whether to use Gerrit's "auto-merge" feature.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.

    Returns:
      bool: True if the transaction succeeded, false if the file didn't change.

    Raises:
      TooManyAttempts: if the number of attempts exceeds |retries|.
    """

    def update_callback():
      self.m.file.remove('try remove existing file', dest)
      self.m.file.write_raw('write file', dest, data)
      if not self.m.git.diff_check(dest):
        return False
      self.m.git.add([dest])
      self.m.git.commit(message, files=[dest])
      return True

    return self.update_ref(remote, update_callback, automerge=automerge,
                           ref=ref)
