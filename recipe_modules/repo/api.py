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

MANIFEST_MOCK = """
    <manifest>
      <project path="SAMPLE" revision="FROM_REV"/>
    </manifest>
  """

ManifestDiff = namedtuple('ManifestDiff', ['name', 'path', 'from_rev', 'to_rev'])

ProjectInfo = namedtuple('ProjectInfo', ['name', 'path', 'remote', 'branch'])


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  ManifestDiff = ManifestDiff

  @property
  def repo_path(self):
    return self.m.depot_tools.repo_resource('repo')

  def _find_root(self):
    """Starting from cwd, find an ancestor with a '.repo' subdir."""
    candidate = self.m.context.cwd.join()  # .join() makes a copy to mutate
    while True:
      if self.m.path.exists(candidate.join('.repo')):
        return candidate
      if candidate.pieces:
        candidate.pieces = candidate.pieces[:-1]
      else:
        return None

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

  def _clear_git_locks(self):
    """Removes any git locks found in the entire repo checkout."""

    repo_cmd = [
        'find', '.repo/', '-type', 'f', '-name', '*.lock', '-print', '-delete'
    ]
    self.m.step('clear repo locks', repo_cmd, infra_step=True)

    try:
      git_cmd = [
          'forall', '--ignore-missing', '-j', '32', '-c', 'find', '.git/',
          '-type', 'f', '-name', '*.lock', '-print', '-delete'
      ]
      self._step(git_cmd, 'clear git locks')
    except recipe_api.StepFailure: # pragma: nocover
      # try again without the --ignore-missing
      git_cmd = [
          'forall', '-j', '32', '-c', 'find', '.git/',
          '-type', 'f', '-name', '*.lock', '-print', '-delete'
      ]
      self._step(git_cmd, 'retry clear git locks')


  def init(self, manifest_url, _kwonly=(), manifest_branch=None, reference=None,
           groups=None, depth=None, repo_url=None):
    """Executes 'repo init' with the given arguments.

    Args:
      * manifest_url (str): URL of the manifest repository to clone.
      * manifest_branch (str): Manifest repository branch to checkout.
      * reference (str): Location of a mirror directory to bootstrap sync.
      * groups (list): Groups to checkout (see `repo init --groups`).
      * depth (int): Create a shallow clone of the given depth.
      * repo_url (str): URL of the repo repository.
    """
    assert _kwonly is (), 'init accepts only 1 positional arg'
    cmd = ['init', '--manifest-url', manifest_url, '--groups', 'all']
    if repo_url is not None:
      cmd += ['--manifest-branch', manifest_branch]
    if reference is not None:
      cmd += ['--reference', reference]
    if groups is not None:
      assert not isinstance(groups, types.StringTypes)
      cmd += ['--groups', ','.join(groups)]
    if depth is not None:
      cmd += ['--depth', '%d' % depth]
    if repo_url is not None:
      cmd += ['--repo-url', repo_url]
    self._step(cmd)
    self._clear_git_locks()

    if self.m.context.cwd:
      self.m.path.mock_add_paths(self.m.context.cwd.join('.repo'))

  def sync(self, _kwonly=(), force_sync=False, detach=False,
           current_branch=False, jobs=None, manifest_name=None, no_tags=False,
           optimized_fetch=False, cache_dir=None):
    """Executes 'repo sync' with the given arguments.

    Args:
      * force_sync (bool): Overwrite existing git directories if needed.
      * detach (bool): Detach projects back to manifest revision.
      * current_branch (bool): Fetch only current branch.
      * jobs (int): Projects to fetch simultaneously.
      * manifest_name (str): Temporary manifest to use for this sync.
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
    if manifest_name is not None:
      cmd += ['--manifest-name', manifest_name]
    if no_tags:
      cmd += ['--no-tags']
    if optimized_fetch:
      cmd += ['--optimized-fetch']
    if cache_dir is not None:
      cmd += ['--cache-dir', cache_dir]
    self._step(cmd)

  def sync_manifest(self, manifest_data, **kwargs):
    """Sync to the given manifest file data.

    Args:
      * manifest_data (str): Manifest XML data to use for the sync.
      * kwargs: Keyword arguments to pass to 'repo.sync'.
    """
    repo_root = self._find_root()
    assert repo_root is not None, 'no repo root found'

    manifest_path = self.m.path.mkstemp('manifest')
    self.m.file.write_raw('write manifest', manifest_path, manifest_data)

    repo_manifests_path = repo_root.join('.repo', 'manifests')
    manifest_relpath = os.path.relpath(
        str(manifest_path), str(repo_manifests_path))
    self.sync(manifest_name=manifest_relpath, **kwargs)

  def start(self, branch, projects=None):
    """Start a new branch in the given projects, or all projects if not set.

    Args:
      branch (str): The new branch name.
      projects (list[str]): The projects for which to start a branch.
    """
    cmd = ['start', branch]
    if projects is not None:
      cmd.extend(projects)
    else:
      cmd.append('--all')
    self._step(cmd)

  def project_infos(self, projects=[]):
    """Uses 'repo forall' to gather project information.

    Args:
      projects (List[str]): Project names or paths to return info for. Defaults
        to all projects.

    Returns:
      List[ProjectInfo]: Requested project infos.
    """

    def step_test_data():
      data = '\n'.join('%s|src/%s|cros|refs/heads/master' % (p, p)
                       for p in projects or ['a', 'b', 'c'])
      return self.m.raw_io.test_api.stream_output(data)

    cmd = ['forall'] + projects
    cmd += ['-c', 'echo $REPO_PROJECT\|$REPO_PATH\|$REPO_REMOTE\|$REPO_RREV']
    step_data = self._step(cmd,
                           stdout=self.m.raw_io.output(add_output_log=True),
                           step_test_data=step_test_data)

    infos = []
    for line in step_data.stdout.strip().split('\n'):
      name, path, remote, rrev = line.split('|')
      branch = None
      if rrev.startswith('refs/heads/'):
        branch = rrev
      infos.append(ProjectInfo(name, path, remote, branch))
    return infos

  def project_info(self, projects):
    """Use 'repo forall' to gather project information for one project.

    Args:
      project (str|Path): Project name or path to return info for.

    Returns:
      ProjectInfo: The request project info.
    """
    project_infos = self.project_infos(projects=projects)
    assert len(set(project_infos)) == 1, 'expected one project'
    return project_infos[0]

  def manifest_snapshot(self):
    """Uses repo to create a manifest snapshot and returns it as a string.

    Returns:
      str: The manifest XML as a string.
    """
    step_test_data = lambda: self.m.raw_io.test_api.stream_output('<manifest></manifest>')
    step_data = self._step(['manifest', '-r'],
                           stdout=self.m.raw_io.output(add_output_log=True),
                           step_test_data=step_test_data)
    return step_data.stdout.strip()

  def diff_remote_and_local_manifests(self, from_manifest_url,
                                      from_manifest_ref, to_manifest_str):
    """Diffs the remote manifest against the local manifest string.

    Diffs the 'snapshot.xml' at the given `from_manifest_url` at the ref
    `from_manifest_ref` against the local `to_manifest_str`.

    Args:
      from_manifest_url (str): The manifest repo url to checkout.
      from_manifest_ref (str): The manifest ref to checkout.
      to_manifest_str (str): The string XML for the to manifest.

    Returns:
      List[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
      changed project (excludes added/removed projects).
    """
    with self.m.step.nest('diff remote and local manifest') as step:
      self.m.git.fetch_ref(from_manifest_url, from_manifest_ref)
      from_xml = self.m.git.show_file('FETCH_HEAD', 'snapshot.xml',
                                      test_contents=MANIFEST_MOCK)

      if from_xml is None:
        step.presentation.step_text = 'no remote manifest found'
        step.presentation.status = 'WARNING'
        return None

      diffs = self.m.repo.diff_manifests(from_xml, to_manifest_str)

      if not diffs:
        step.presentation.step_text = 'no manifest diffs from remote to local'
        step.presentation.status = 'WARNING'

      return diffs

  def diff_manifests(self, from_manifest_str, to_manifest_str):
    """Diffs the two manifests and returns an array of differences.

    Given the two manifest XML strings, generates an array of `ManifestDiff`.
    This only returns **CHANGED** projects, it skips over projects that were
    added or deleted.

    Args:
      from_manifest_str (str): The from manifest XML string
      to_manifest_str (str):The to manifest XML string.

    Returns:
      List[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
      changed project (excludes added/removed projects).
    """

    def project_paths(xml_data):
      xml = ElementTree.fromstring(xml_data)
      attrs = [proj.attrib for proj in xml.iterfind('project')]
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
      from_name = from_attrs['name']
      from_revision = from_attrs['revision']
      to_revision = to_paths[from_path]['revision']
      if from_revision == to_revision:
        # The revision didn't change (aka no CLs landed between the last
        # snapshot and this one for that path.
        continue
      changes.append(
          ManifestDiff(from_name, from_path, from_revision, to_revision))
    return changes

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

  def _git_clean_checkout(self, root_path):
    """Ensure the given repo does not contain untracked files or directories.

    We're assuming that the root path provided has already been validated.

    Args:
      * root_path (Path): Path to the repo root.
    """
    with self.m.step.nest('ensure clean checkout'):
      with self.m.context(cwd=root_path, infra_steps=True):
        try:
          cmd = ['forall', '--ignore-missing', '-j', '32', '-c', 'git', 'clean',
                 '-d', '-f']
          self._step(cmd, stdout=self.m.raw_io.output(add_output_log=True))
        except self.m.step.StepFailure: # pragma: nocover
          # try again without the --ignore-missing
          cmd = ['forall', '-j', '32', '-c', 'git', 'clean',
                 '-d', '-f']
          self._step(cmd, stdout=self.m.raw_io.output(add_output_log=True))


  def ensure_synced_checkout(self, root_path, manifest_url, init_opts=None,
                             sync_opts=None):
    """Ensure the given repo checkout exists and is synced.

    Args:
      * root_path (Path): Path to the repo root.
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
    """
    with self.m.step.nest('ensure synced checkout'):
      self.m.file.ensure_directory('ensure root path', root_path)
      with self.m.context(cwd=root_path, infra_steps=True):
        # Remove .repo/manifests and .repo/manifests.git to avoid potential
        # problems when switching to a different manifest repo or branch.
        for manifest_dir in ('manifests', 'manifests.git'):
          self.m.file.rmtree('remove .repo/%s' % manifest_dir,
                             root_path.join('.repo', manifest_dir))

        self.m.repo.init(manifest_url, **(init_opts or {}))
        self.m.repo._git_clean_checkout(root_path)
        self.m.repo._binary_selfupdate(root_path)
        self.m.repo.sync(**(sync_opts or {}))

      # Sanity check since `repo init` will happily reuse a repository in the
      # cwd's ancestor directories.
      assert self.m.path.exists(root_path.join('.repo')), '.repo not created!'

  def _binary_selfupdate(self, root_path):
    """Issues a repo selfupdate to update the binary.

    Args"
      * root_path (Path): Path to the repo root.
    """
    with self.m.step.nest('repo binary update'):
      with self.m.context(cwd=root_path, infra_steps=True):
        cmd = ['selfupdate']
        self._step(cmd, ok_ret='any')
