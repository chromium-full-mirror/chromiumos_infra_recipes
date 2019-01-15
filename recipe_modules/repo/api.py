# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'repo' VCS tool.

See: https://chromium.googlesource.com/external/repo/
"""

from collections import namedtuple
import os
import types

from recipe_engine import recipe_api
from xml.etree import cElementTree as ElementTree


ManifestDiff = namedtuple('ManifestDiff', ['path', 'from_rev', 'to_rev'])


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  @property
  def repo_path(self):
    return self.m.depot_tools.package_repo_resource('repo')

  def _step(self, args, name=None, **kwargs):
    """Executes 'repo' with the supplied arguments.

    Args:
      * args (list): A list of arguments to supply to 'repo'.
      * name (str): The name of the step. If None, generate from the args.
      * kwargs: See 'step.__call__'.

    Returns:
      StepData: See 'step.__call__'.
    """
    if name is None:
      name = 'repo'
      # Add first non-flag argument to name.
      for arg in args:
        if isinstance(arg, types.StringTypes) and arg[:1] != '-':
          name += ' ' + arg
          break
    kwargs.setdefault('infra_step', True)
    return self.m.step(name, [self.repo_path] + args, **kwargs)

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
    self._step(cmd)

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
    self._step(cmd)

  def manifest_snapshot(self):
    """Uses repo to create a manifest snapshot and returns it as a string.

    Returns:
      str: The manifest XML as a string.
    """
    step_test_data = lambda: self.m.raw_io.test_api.stream_output(
      '<manifest></manifest>')
    step_data = self._step(['manifest', '-r'],
                           stdout=self.m.raw_io.output(add_output_log=True),
                           step_test_data=step_test_data)
    return step_data.stdout.strip()

  def diff_manifests(self, from_manifest_str, to_manifest_str):
    """Diffs the two manifests and returns an array of differences.

    Given the two manifest XML strings, generates an array of `ManifestDiff`.
    This only returns **CHANGED** projects, it skips over projects that were
    added or deleted.

    Args:
      * from_manifest_str (str): The from manifest XML string
      * to_manifest_str (str):The to manifest XML string.

    Returns:
      List[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
      changed project (excludes added/removed projects).
    """
    def project_paths(xml_data):
      xml = ElementTree.fromstring(xml_data)
      attrs = [proj.attrib for proj in xml.iterfind ('project')]
      # Make sure `path` is set, use `name` if `path` is missing
      for attr in attrs:
        attr['path'] = attr.get('path', attr.get('name'))
      # Key them by path
      return {attr['path']: attr for attr in attrs}

    from_paths = project_paths(from_manifest_str)
    to_paths = project_paths(to_manifest_str)
    changes = []
    for from_path, from_attrs in from_paths.items():
      if from_path not in to_paths:
        # Project was deleted, we don't care. Move on, nothing to see here!
        continue
      from_revision = from_attrs['revision']
      to_revision = to_paths[from_path]['revision']
      if from_revision == to_revision:
        # The revision didn't change (aka no CLs landed between the last
        # snapshot and this one for that path.
        continue
      changes.append(ManifestDiff(from_path, from_revision, to_revision))
    return changes

  def _find_root(self):
    """Starting from cwd, find an ancestor with a '.repo' subdir."""
    candidate = self.m.context.cwd.join()  # .join() makes a copy to mutate
    while candidate.pieces:
      if self.m.path.exists(candidate.join('.repo')):
        return candidate
      candidate.pieces = candidate.pieces[:-1]
    return None

  def diff_manifests_informational(self, old_manifest_path, new_manifest_path):
    """Informational step that logs a "manifest diff".

    Args:
      old_manifest_path (Path): Path to old manifest file.
      new_manifest_path (Path): Path to new manifest file.
    """
    name = 'manifest diff'
    # Manifest paths must be relative to the current repo .repo/manifests dir.
    repo_root = self._find_root()
    if repo_root is None:
      step = self.m.step(name, [])
      step.presentation.step_text = 'manifest diff failed; no repo root found'
      return
    manifests_dir = self.m.path.abspath(repo_root.join('.repo', 'manifests'))

    cmd = [
        'diffmanifests',
        os.path.relpath(str(old_manifest_path), manifests_dir),
        os.path.relpath(str(new_manifest_path), manifests_dir),
    ]
    self._step(cmd, name=name)
