# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for updating remote git repositories transactionally."""

from recipe_engine import recipe_api


class Error(recipe_api.StepFailure):
  """Base error for this module."""


class TooManyAttempts(Error):
  """The transaction could not be completed in the allowed number of retries."""

  def __init__(self):
    super(TooManyAttempts, self).__init__(self.__doc__)


class GitTxnApi(recipe_api.RecipeApi):
  """A module for executing git transactions."""

  def update_ref(self, remote, update_callback, ref=None, retries=3,
                 automerge=False):
    """Transactionally update a remote git repository ref.

    |update_callback| will be called and should update the checked out HEAD by
    e.g. committing a new change. Then this new HEAD will be pushed back to the
    |remote| |ref|. If this push fails because the remote ref was modified in
    the meantime, the new ref is fetched and checked out, and the process will
    repeat up to |retries| times.

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
      retries (int): Number of update attempts to make before failing.
      automerge (bool): Whether to use Gerrit's "auto-merge" feature.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.

    Returns:
      bool: True if the transaction succeeded, false if it explicitly aborts.

    Raises:
      TooManyAttempts: if the number of attempts exceeds |retries|.
    """
    ref = ref or self.m.git.remote_head(self.m.repo.project_info().remote)

    if not ref.startswith('refs/'):
      ref = 'refs/heads/%s' % ref
    for i in range(retries):
      message = 'git transaction'
      if i > 0:
        message += ' retry %d of %d' % (i, retries - 1)
      with self.m.step.nest(message) as presentation:
        if update_callback() is False:
          presentation.step_text = 'Transaction aborted without failure.'
          return False

        try:
          dest_ref = ref
          if automerge:
            # See https://gerrit-review.googlesource.com/Documentation/user-upload.html#auto_merge
            dest_ref = 'refs/for/%s%%notify=NONE,submit' % dest_ref
          dest_ref = 'HEAD:%s' % dest_ref
          self.m.git.push(remote, dest_ref, capture_stdout=True, retry=False)
          return True
        except recipe_api.StepFailure as ex:
          # Only retry on remote 'rejected' errors.
          if ex.retcode == 1 and 'rejected' in ex.result.stdout:
            ex.result.presentation.status = 'SUCCESS'

            self.m.git.fetch_ref(remote, ref)
            self.m.git.checkout('FETCH_HEAD', force=True)
          else:
            raise

    raise TooManyAttempts()

  def update_ref_write_file(self, remote, message, dest, data, ref=None,
                            **kwargs):
    """Transactionally update a file in a remote git repository ref.

    See 'self.update_ref'. Instead of running a callback, this will attempt to
    update the contents of a file.

    Args:
      remote (str): The remote repository to update.
      message (str): The commit message to use.
      dest (Path): The path of the file to write.
      data (str): The data to write.
      kwargs: See 'self.update_ref'.
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

    return self.update_ref(remote, update_callback, ref=ref, **kwargs)
