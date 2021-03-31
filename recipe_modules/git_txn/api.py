# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for updating remote git repositories transactionally."""

from recipe_engine import recipe_api


class Error(recipe_api.StepFailure):
  """Base error for this module."""


class GitTxnApi(recipe_api.RecipeApi):
  """A module for executing git transactions."""

  def update_ref(self, update_callback, step_name='git transaction', ref=None):
    """Transactionally update a remote git repository ref.

    |update_callback| will be called and should update the checked out HEAD by
    e.g. committing a new change.

    The common case is that there's no issue updating the ref, so we don't do
    a fetch and checkout before attempting to update.  This means that
    the function assumes that the repo is already checked out to the target
    ref.

    This step expects to be run with `cwd` inside a git repo.

    Args:
      update_callback (callable): The callback function that will update the
          local repo's HEAD. The callback is passed no arguments. If the
          callback returns False the update will be cancelled but succeed.
      ref (str): The remote ref to update. If it does not start with 'refs/' it
          will be treated as a branch name. If not specified, the HEAD ref for
          the remote of the current repo project will be used.

    Returns:
      bool: True if the transaction succeeded, false if it explicitly aborts.
    """
    ref = ref or self.m.git.remote_head(self.m.repo.project_info().remote)
    if not ref.startswith('refs/for/'):
      ref = 'refs/for/%s' % ref
    with self.m.step.nest(step_name) as presentation:
      if update_callback() is False:
        presentation.step_text = 'Transaction aborted without failure.'
        return False

      path = self.m.git.repository_root()
      change = self.m.gerrit.create_change(path, branch=ref)
      label = {self.m.gerrit.Label.BOT_COMMIT: 1}
      self.m.gerrit.set_change_labels(change, label, ref=ref)
      self.m.gerrit.submit_change(change)
      return True

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

    return self.update_ref(update_callback, ref=ref)
