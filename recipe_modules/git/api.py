# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with git."""

import types

from recipe_engine import recipe_api


class GitApi(recipe_api.RecipeApi):
  """A module for interacting with git."""

  def _step(self, args, name=None, **kwargs):
    """Executes 'git' with the supplied arguments.

    Args:
      * args (list): A list of arguments to supply to 'git'.
      * name (str): The name of the step. If None, generate from the args.
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
    kwargs.setdefault('infra_step', True)
    return self.m.step(name, ['git'] + args, **kwargs)

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

    step_test_data = lambda: self.m.raw_io.test_api.stream_output('deadbeef\n')
    step_data = self._step(['rev-parse', 'FETCH_HEAD'],
                           stdout=self.m.raw_io.output(),
                           step_test_data=step_test_data)
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
    if self.m.dev.dryrun:
      args += ['--dryrun']
    args += [remote, refspec]
    return self._step(args, stdout=stdout)
