# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'repo' VCS tool.

See: https://chromium.googlesource.com/external/repo/
"""

import types

from recipe_engine import recipe_api


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  @property
  def repo_path(self):
    return self.m.depot_tools.package_repo_resource('repo')

  def __call__(self, args, name=None):
    """Executes 'repo' with the supplied arguments.

    Args:
      * args (list): A list of arguments to supply to 'repo'.
      * name (str): The name of the step. If None, generate from the args.

    Returns:
      See 'step.__call__'.
    """
    if name is None:
      name = 'repo %s' % args[0]
    return self.m.step(name, [self.repo_path] + args)

  def init(self, manifest_url, _kwonly=(), manifest_branch=None, groups=None,
           depth=None, repo_url=None):
    """Executes 'repo init' with the given arguments.

    Args:
      * manifest_url (str): URL of the manifest repository to clone.
      * manifest_branch (str): Manifest repository branch to checkout.
      * groups (list): Groups to checkout (see `repo init --groups`).
      * depth (int): Create a shallow clone of the given depth.
      * repo_url (str): URL of the repo repository.
    """
    assert _kwonly is (), 'init accepts only 1 positional arg'
    cmd = ['init', '--manifest-url', manifest_url]
    if repo_url is not None:
      cmd += ['--manifest-branch', manifest_branch]
    if groups is not None:
      assert not isinstance(groups, types.StringTypes)
      cmd += ['--groups', ','.join(groups)]
    if depth is not None:
      cmd += ['--depth', '%d' % depth]
    if repo_url is not None:
      cmd += ['--repo-url', repo_url]
    self(cmd)

  def sync(self, _kwonly=(), force_sync=False, detach=False,
           current_branch=False, jobs=None, no_tags=False,
           optimized_fetch=False, cache_dir=None):
    """Executes 'repo sync' with the given arguments.

    Args:
      * force_sync (bool): Overwrite existing git directories if needed.
      * detach (bool): Detach projects back to manifest revision.
      * current_branch (bool): Fetch only current branch.
      * jobs (int): Projects to fetch simultaneously.
      * no_tags (bool): Don't fetch tags.
      * optimized_fetch (bool): Only fetch projects if revision doesn't exist.
      * cache_dir (Path): Use git-cache with this cache directory.
    """
    assert _kwonly is (), 'sync accepts no positional args'
    cmd = ['sync']
    if force_sync:
      cmd += ['--force-sync']
    if detach:
      cmd += ['--detach']
    if current_branch:
      cmd += ['--current-branch']
    if jobs is not None:
      cmd += ['--jobs', '%d' % jobs]
    if no_tags:
      cmd += ['--no-tags']
    if optimized_fetch:
      cmd += ['--optimized-fetch']
    if cache_dir is not None:
      cmd += ['--cache-dir', cache_dir]
    self(cmd)
