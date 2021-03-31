# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with git cl."""

import re

from recipe_engine import recipe_api


class GitClApi(recipe_api.RecipeApi):
  """A module for interacting with git cl."""

  def __call__(self, *args, **kwargs):
    # Verify and adjust kwargs so they align with depot_tools/git_cl.
    assert 'stdout' not in kwargs, 'cannot set stdout'
    step_name = kwargs.pop('step_name', None)
    if step_name is not None:
      kwargs['name'] = step_name

    with self.m.depot_tools.on_path():
      return self.m.depot_tools_git_cl(
          *args, stdout=self.m.raw_io.output(), **kwargs
      ).stdout.strip()

  def __getattr__(self, name):
    attr = getattr(self.m.depot_tools_git_cl, name)

    assert callable(attr), 'unexpected uncallable attr'

    # Ensure depot_tools is on path.
    def wrapper(*args, **kwargs):
      with self.m.depot_tools.on_path():
        return attr(*args, **kwargs)

    return wrapper

  def upload(self, topic=None, reviewers=None, ccs=None, hashtags=None,
             send_mail=False, target_branch=None, **kwargs):
    """Run `git cl upload`.

    --force and --bypass-hooks are always set to remove the need to enter
    confirmations and address nits.

    Args:
      topic (str): Optional --topic to set.
      reviewers (list[str]): Optional list of --reviewers to set.
      ccs (list[str]): Optional list of --cc to set.
      hashtags (list[str]): Optional list of --hashtags to set.
      send_mail (bool): If true, set --send-mail.
      target_branch (str): Optional --target-branch to send to.
      kwargs (dict): Forwarded to recipe_engine/step. May NOT set stdout.

    Returns:
      str: The command output.
    """
    args = ['--bypass-hooks', '--force']

    if topic is not None:
      args.append('--topic')
      args.append(topic)

    if reviewers is not None:
      for reviewer in reviewers:
        args.append('--reviewers')
        args.append(reviewer)

    if ccs is not None:
      for cc in ccs:
        args.append('--cc')
        args.append(cc)

    if hashtags is not None:
      for hashtag in hashtags:
        args.append('--hashtag')
        args.append(hashtag)

    if send_mail:
      args.append('--send-mail')

    if target_branch is not None:
      args.append('--target-branch')
      args.append(target_branch)

    return self('upload', args, **kwargs)

  def status(self, field=None, fast=False, **kwargs):
    """Run `git cl status` with given arguments.

    Args:
      field: Set --field to this value.
      fast: Set --fast.
      kwargs: Passed to recipe_engine/step. May NOT set stdout.

    Returns:
      str: The command output.
    """
    args = []

    if field is not None:
      args.append('--field')
      args.append(field)

    if fast:
      args.append('--fast')

    return self('status', args, **kwargs)
