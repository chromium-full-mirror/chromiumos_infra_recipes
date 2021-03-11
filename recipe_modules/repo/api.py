# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'repo' VCS tool.

See: https://chromium.googlesource.com/external/repo/
"""

from google.protobuf.json_format import MessageToDict
from collections import namedtuple
import re
import types

from PB.chromiumos.repo_cache_state import RepoState
from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from xml.etree import cElementTree as ElementTree

MANIFEST_MOCK = """
    <manifest>
      <project path="SAMPLE" revision="FROM_REV"/>
    </manifest>
  """

ManifestDiff = namedtuple('ManifestDiff',
                          ['name', 'path', 'from_rev', 'to_rev'])


class ProjectInfo(
    namedtuple('ProjectInfo', ['name', 'path', 'remote', 'branch', 'rrev'])):

  __slots__ = ()

  @property
  def branch_name(self):
    """Return the branch name."""
    return (self.branch[len('refs/heads/'):]
            if self.branch.startswith('refs/heads/') else self.branch)


LocalManifest = namedtuple('LocalManifest', ['repo', 'path'])


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  ManifestDiff = ManifestDiff
  ProjectInfo = ProjectInfo
  LocalManifest = LocalManifest

  def __init__(self, properties, *args, **kwargs):
    super(RepoApi, self).__init__(*args, **kwargs)
    self._disable_source_cache_health = properties.disable_source_cache_health

  def initialize(self):
    self._binary_updated = False
    self._disable_source_cache_health |= (
        'chromeos.repo.disable_source_cache_health' in
        self.m.cros_infra_config.experiments)

  @property
  def repo_path(self):
    return self.m.depot_tools.repo_resource('repo')

  @property
  def disable_source_cache_health(self):
    return self._disable_source_cache_health

  def _find_root(self):
    """Starting from cwd, find an ancestor with a '.repo' subdir."""
    # We need a copy of cwd that we can modify. join() with no arguments
    # returns the instance, so we add an element, and then remove it.
    candidate = self.m.context.cwd.join('force-copy')
    candidate.pieces = candidate.pieces[:-1]
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
    # Always run with depot_tools.on_path, since repo depends on it.
    with self.m.depot_tools.on_path():
      return self.m.step(name, [self.repo_path] + args, **kwargs)

  def _clear_git_locks(self, projects=None):
    """Removes git locks found in the repo checkout.

    Removes git locks in the repo checkout. The specifying of projects
    is provided as an optimization for applications that are dealing with
    a subset of the projects. The speedup can be substantial.

    Args:
      * projects (List[str]): Projects to limit the repo forall deleting of
      locks to, or None to clear all project locks.
    """
    repo_cmd = [
        'find', '.repo/', '-type', 'f', '-name', '*.lock', '-print', '-delete'
    ]
    self.m.step('clear repo locks', repo_cmd, infra_step=True)

    git_cmd = ['forall'] + (projects or [])
    base_args = [
        '-j', '32', '-c', 'find', '.', '-type', 'f', '-path', './.git/*.lock',
        '-print', '-delete'
    ]

    try:
      self._step(git_cmd + ['--ignore-missing'] + base_args, 'clear git locks')
    except recipe_api.StepFailure:  # pragma: nocover
      self.m.step.active_result.presentation.status = self.m.step.WARNING
      try:
        self._step(git_cmd + base_args, 'retry clear git locks')
      except recipe_api.StepFailure:  # pragma: nocover
        self.m.step.active_result.presentation.status = self.m.step.WARNING
        self._step(['forall'] + base_args,
                   'retry clear git locks without projects')

  def version(self):
    """Prints the current version information of repo."""
    self._step(['version'], 'repo version', infra_step=True)

  def init(self, manifest_url, _kwonly=(), manifest_branch='', reference=None,
           groups=None, depth=None, repo_url=None, repo_branch=None,
           local_manifests=None, manifest_name=None, projects=None,
           verbose=False, clean=True):
    """Executes 'repo init' with the given arguments.

    Args:
      * manifest_url (str): URL of the manifest repository to clone.
      * manifest_branch (str): Manifest repository branch to checkout.
      * reference (str): Location of a mirror directory to bootstrap sync.
      * groups (list): Groups to checkout (see `repo init --groups`).
      * depth (int): Create a shallow clone of the given depth.
      * repo_url (str): URL of the repo repository.
      * repo_branch (str): Repo binary branch to use.
      * local_manifests (list[LocalManifest]): Local manifests to add. See
      https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md#local-manifests.
      * manifest_name (Path): The manifest file to use.
      * projects (List[str]): Projects of concern or None if all projects are of
      concern. Used to limit work where possible such as only clearing git locks
      in these projects.
      * verbose (bool): Whether to produce verbose output.
    """
    assert _kwonly is (), 'init accepts only 1 positional arg'
    cmd = ['init', '--manifest-url', manifest_url, '--groups', 'all']
    if manifest_branch:
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
    if repo_branch is not None:
      cmd += ['--repo-branch', repo_branch, '--no-repo-verify']
    if manifest_name:
      cmd += ['--manifest-name', manifest_name]
    # TODO(b/176082897) Force --verbose while debugging.
    if verbose or True:
      cmd += ['--verbose']
    self._step(cmd, timeout=15 * 60)
    self._binary_selfupdate(self.m.context.cwd)
    if not clean:
      self._clear_git_locks()

    if self.m.context.cwd:
      self.m.path.mock_add_paths(self.m.context.cwd.join('.repo'))

    if local_manifests is not None:
      # Local manifests should be installed under .repo/local_manifests/*.xml.
      # The .repo dir should be created by the above init.
      assert self.m.path.exists(self.m.context.cwd.join('.repo'))
      local_manifest_dir = self.m.context.cwd.join('.repo', 'local_manifests')
      self.m.file.ensure_directory(name='ensure local manifest dir',
                                   dest=local_manifest_dir)

      for i, local_manifest in enumerate(local_manifests):
        manifest_data = self.m.gitiles.download_file(
            local_manifest.repo, local_manifest.path, branch='HEAD',
            step_test_data=self.test_api.local_manifest_step_test_data)
        self.m.file.write_raw(
            name='write local manifest',
            # If there is more than one local manifest, it needs a different
            # name.
            dest=local_manifest_dir.join('local_manifest_{}.xml'.format(i)
                                         if i else 'local_manifest.xml'),
            data=manifest_data,
        )

  def sync(self, _kwonly=(), force_sync=False, detach=False,
           current_branch=False, jobs=None, manifest_name=None, no_tags=False,
           optimized_fetch=False, cache_dir=None, timeout=None,
           retry_fetches=None, projects=None, verbose=False,
           no_manifest_update=False):
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
      * retry_fetches (int): The number of times to retry retriable fetches.
      * projects (List[str]): Projects to limit the sync to, or None to sync
        all projects.
      * verbose (bool): Whether to produce verbose output.
      * no_manifest_update (bool): Whether to disable updating the manifest.
    """
    assert _kwonly is (), 'sync accepts no positional args'
    cmd = ['sync']
    if force_sync:
      cmd += ['--force-sync']
    if detach:
      cmd += ['--detach']
    if current_branch:
      cmd += ['--current-branch']
    if jobs:
      cmd += ['--jobs', '%d' % jobs]
    if manifest_name:
      cmd += ['--manifest-name', manifest_name]
    if no_tags:
      cmd += ['--no-tags']
    if optimized_fetch:
      cmd += ['--optimized-fetch']
    if cache_dir:
      cmd += ['--cache-dir', cache_dir]
    if retry_fetches:
      cmd += ['--retry-fetches', '%d' % retry_fetches]
    # TODO(b/176082897) Force --verbose while debugging.
    if verbose or True:
      cmd += ['--verbose']
    if no_manifest_update:
      cmd += ['--no-manifest-update']
    if projects:
      cmd += projects
    self._step(cmd, name=None, timeout=timeout)

  def sync_manifest(self, manifest_url, manifest_data, **kwargs):
    """Sync to the given manifest file data.

    Args:
      * manifest_url (str): URL of manifest repo to sync to (for repo init)
      * manifest_data (str): Manifest XML data to use for the sync.
      * kwargs: Keyword arguments to pass to 'repo.sync'.
    """
    repo_root = self._find_root()
    assert repo_root is not None, 'no repo root found'

    manifest_path = repo_root.join('.repo', 'tmp_manifest')
    self.m.file.write_raw('write manifest', manifest_path, manifest_data)

    repo_manifests_path = repo_root.join('.repo', 'manifests')
    manifest_relpath = self.m.path.relpath(manifest_path, repo_manifests_path)
    init_opts = {"projects": kwargs.get("projects", None)}
    self.init(manifest_url, manifest_name=manifest_relpath, **init_opts)
    self.sync(**kwargs)

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

  def abandon(self, branch, projects=None):
    """Abandon the branch in the given projects, or all projects if not set.

    Args:
      branch (str): The branch to abandon.
      projects (list[str]): The projects for which to abandon the branch.
    """
    cmd = ['abandon', branch]
    if projects is not None:
      cmd.extend(projects)
    else:
      cmd.append('--all')
    self._step(cmd)

  def project_infos(self, projects=None, regexes=None, test_data=None):
    """Uses 'repo forall' to gather project information.

    Note that if both projects and regexes are specified the resultant
    ProjectInfos are the union, without duplicates, of what each would
    return separately.

    Args:
      projects (List[str]): Project names or paths to return info for. Defaults
        to all projects.
      regexes (List[str]): list of regexes for matching projects. The matching
        is the same as in `repo forall --regex regexes...`.
      test_data (str): Test data for the step: the output from repo forall, or
          None for the default.

    Returns:
      List[ProjectInfo]: Requested project infos.
    """
    projects = projects or []
    regexes = regexes or []

    if test_data is None:
      test_data = self.test_api.project_infos_test_data(
          [dict(project=p) for p in projects or self.test_api.test_projects])
    step_test_data = lambda: self.m.raw_io.test_api.stream_output(test_data)

    cmd = ['forall'] + projects
    if regexes:
      cmd += ['--regex'] + regexes
    cmd += [
        '-c',
        'echo $REPO_PROJECT\|$REPO_PATH\|$REPO_REMOTE\|$REPO_RREV\|$REPO_UPSTREAM'
    ]
    step_data = self._step(cmd,
                           stdout=self.m.raw_io.output(add_output_log=True),
                           step_test_data=step_test_data)

    infos = []
    lines = step_data.stdout.strip().split('\n')

    # If nothing was matched, return the empty infos.
    if len(lines) == 1 and lines[0] == '':
      return infos

    for line in lines:
      name, path, remote, rrev, upstream = line.split('|')

      branch = None
      if upstream:
        branch = upstream
      elif rrev.startswith('refs/heads/'):
        branch = rrev

      infos.append(ProjectInfo(name, path, remote, branch, rrev))
    return infos

  def project_info(self, project=None):
    """Use 'repo forall' to gather project information for one project.

    Args:
      project (str|Path): Project name or path to return info for. If None, then
      use the cwd as the path for the project.

    Returns:
      ProjectInfo: The request project info.
    """
    project = project or self.m.context.cwd
    project_infos = self.project_infos(projects=[project])
    assert len(set(project_infos)) == 1, 'expected one project'
    return project_infos[0]

  def ensure_pinned_manifest(self, projects=None, regexes=None, test_data=None,
                             step_name=None):
    """Ensure that we know the revision info for all projects.

    If the manifest is not pinned, a pinned manifest is created and logged.

    Args:
      projects (List[str]): Project names or paths to return info for. Defaults
        to all projects.
      regexes (List[str]): list of regexes for matching projects. The matching
        is the same as in `repo forall --regex regexes...`.
      test_data (str): Test data for the step: the output from repo forall, or
          None for the default.  This is passed to project_infos().

    Returns:
      (str): The manifest XML as a string, or None if the manifest is already
      pinned.
    """
    with self.m.step.nest(step_name or 'ensure manifest is pinned') as pres:
      infos = self.project_infos(projects=projects, regexes=regexes,
                                 test_data=test_data)
      if not all(re.match(r'[0-9a-fA-F]{40}$', x.rrev) for x in infos):
        manifest = self.manifest(pinned=True)
        pres.logs['pinned-manifest.xml'] = [manifest]
        return manifest
      return None

  def manifest(self, manifest_file=None, test_data=None, pinned=False,
               step_name=None):
    """Uses repo to create a manifest and returns it as a string.

    By default uses the internal .repo manifest, but can optionally take
    another manifest to use.

    Args:
      manifest_file (Path): If given, path to alternate manifest file to use.
      pinned (bool): Whether to create a pinned (snapshot) manifest.
      test_data (str): Test data for the step: the contents of the manifest, or
          None for the default.
      step_name (str): The name for the step, or None.

    Returns:
      str: The manifest XML as a string.
    """
    step_test_data = lambda: self.m.raw_io.test_api.stream_output(
        test_data or '<manifest></manifest>')

    cmd = ['manifest']
    if pinned:
      cmd += ['-r']
    if manifest_file:
      cmd += ['-m', manifest_file]

    step_data = self._step(cmd,
                           stdout=self.m.raw_io.output(add_output_log=True),
                           step_test_data=step_test_data, name=step_name)
    return step_data.stdout.strip()

  def diff_remote_and_local_manifests(self, from_manifest_url,
                                      from_manifest_ref, to_manifest_str,
                                      test_from_data=None,
                                      use_merge_base=False):
    """Diffs the remote manifest against the local manifest string.

    Diffs the 'snapshot.xml' at the given `from_manifest_url` at the ref
    `from_manifest_ref` against the local `to_manifest_str`.

    Args:
      from_manifest_url (str): The manifest repo url to checkout.
      from_manifest_ref (str): The manifest ref to checkout.
      to_manifest_str (str): The string XML for the to manifest.
      test_from_data (str): Test data: The from_manifest contents, or None for
          the default.
      use_merge_base (bool): Whether to adjust the from_ref with `git
          merge-base`.

    Returns:
      List[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
      changed project (excludes added/removed projects).
    """
    with self.m.step.nest('diff remote and local manifest') as presentation:
      self.m.git.fetch_ref(from_manifest_url, from_manifest_ref)
      from_xml = self.m.git.show_file(
          'FETCH_HEAD', 'snapshot.xml', test_contents=test_from_data or
          MANIFEST_MOCK)

      if from_xml is None:
        presentation.step_text = 'no remote manifest found'
        presentation.status = 'WARNING'
        return None

      diffs = self.diff_manifests(from_xml, to_manifest_str,
                                  use_merge_base=use_merge_base)

      if not diffs:
        presentation.step_text = 'no manifest diffs from remote to local'
        presentation.status = 'WARNING'

      return diffs

  def diff_manifests(self, from_manifest_str, to_manifest_str,
                     use_merge_base=False):
    """Diffs the two manifests and returns an array of differences.

    Given the two manifest XML strings, generates an array of `ManifestDiff`.
    This only returns **CHANGED** projects, it skips over projects that were
    added or deleted.

    Args:
      from_manifest_str (str): The from manifest XML string
      to_manifest_str (str):The to manifest XML string.
      use_merge_base (bool): Whether to adjust the from_ref with `git
          merge-base`.

    Returns:
      List[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
      changed project (excludes added/removed projects).
    """

    _test_data_default_remote = 'cros'

    def snapshot_mode(project):
      for annotation in project.iterfind('annotation'):
        if annotation.get('name') == 'snapshot-mode':
          return annotation.get('value')
      return None

    def find_default_remote(xml_data):
      xml = ElementTree.fromstring(xml_data)
      ret = [
          x.attrib.get('remote')
          for x in xml.iterfind('default')
          if x.attrib.get('remote')
      ] + [_test_data_default_remote]
      return ret[0]

    def find_remotes(xml_data):
      xml = ElementTree.fromstring(xml_data)
      remotes = [x.attrib for x in xml.iterfind('remote')] or [{
          'name': _test_data_default_remote
      }]
      for remote in remotes:
        remote.setdefault('alias', remote.get('name'))
      return {remote['name']: remote for remote in remotes}

    def project_paths(xml_data):
      xml = ElementTree.fromstring(xml_data)
      # Some projects may be ignored by annealing. Specifically, the checked
      # out copy of the snapshot branch of the manifest.
      attrs = [
          proj.attrib
          for proj in xml.iterfind('project')
          if snapshot_mode(proj) != 'ignore-diff'
      ]

      # Make sure `path` is set, use `name` if `path` is missing
      for attr in attrs:
        attr['path'] = attr.get('path', attr.get('name'))
      # Key them by path
      return {attr['path']: attr for attr in attrs}

    if use_merge_base:
      repo_root = self._find_root()
    remotes = find_remotes(from_manifest_str)
    from_paths = project_paths(from_manifest_str)
    to_paths = project_paths(to_manifest_str)
    default_remote = find_default_remote(from_manifest_str)
    changes = []
    for from_path, from_attrs in from_paths.items():
      if from_path not in to_paths:
        # Project was deleted, we don't care. Move on, nothing to see here!
        continue
      from_name = from_attrs['name']
      from_revision = from_attrs['revision']
      from_remote = from_attrs.get('remote', default_remote)
      # Not all test data provides remotes, so just pass the remote name along
      # if we don't have a declaration for the remote.
      from_remote = remotes.get(from_remote, {'alias': from_remote})['alias']
      to_revision = to_paths[from_path]['revision']
      if from_revision == to_revision:
        # The revision didn't change (aka no CLs landed between the last
        # snapshot and this one for that path.
        continue
      if use_merge_base:
        # Fetch the from_revision, since it may not be under refs/heads.
        with self.m.step.nest('validate {}'.format(from_path)) as val_pres, \
            self.m.context(cwd=repo_root.join(from_path)):
          self.m.git.fetch(from_remote, [from_revision])
          base = self.m.git.merge_base(from_revision, to_revision,
                                       test_stdout=from_revision)
          val_pres.step_text = (
              from_revision if from_revision == base else '{} => {}'.format(
                  from_revision, base or from_revision))
          from_revision = base or from_revision
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
    manifests_dir = repo_root.join('.repo', 'manifests')

    cmd = [
        'diffmanifests',
        self.m.path.relpath(old_manifest_path, manifests_dir),
        self.m.path.relpath(new_manifest_path, manifests_dir),
    ]
    self._step(cmd, name=name)

  def _git_clean_checkout(self, root_path, projects=None):
    """Ensure the given repo does not contain untracked files or directories.

    We're assuming that the root path provided has already been validated.

    Args:
      * root_path (Path): Path to the repo root.
      * projects (List[str]): Projects to clean or None to clean all projects.
    """
    with self.m.step.nest('ensure clean checkout'), self.m.context(
        cwd=root_path, infra_steps=True):
      cmd = ['forall'] + (projects or [])
      base_args = [
          '--ignore-missing', '-j', '32', '-c', 'git', 'clean', '-d', '-f'
      ]
      try:
        self._step(cmd + base_args,
                   stdout=self.m.raw_io.output(add_output_log=True))
      except recipe_api.StepFailure:  # pragma: nocover
        self.m.step.active_result.presentation.status = self.m.step.WARNING
        self._step(['forall'] + base_args, 'retry clear git locks')

  @property
  def manifest_gitiles_commit(self):
    """Return a Gitiles commit for the repo manifest."""
    with self.m.context(cwd=self._find_root().join('.repo', 'manifests')):
      return self.m.git.gitiles_commit()

  def ensure_synced_checkout(self, root_path, manifest_url, init_opts=None,
                             sync_opts=None, projects=None):
    repo_state_path = root_path.join('.recipes_state.json')
    manifest_branch = (init_opts.get('manifest_branch') or
                       '') if init_opts else ''

    # Get cache state
    if self.m.path.exists(repo_state_path):
      test_proto = None
      if self._test_data.enabled:
        test_proto = RepoState(
            state=self._test_data.get('repo_current_state',
                                      RepoState.STATE_DIRTY),
            manifest_branch=self._test_data.get('repo_manifest_branch',
                                                manifest_branch),
            manifest_url=manifest_url,
        )
      repo_state = self.m.file.read_proto(
          'Read proto from {}'.format(repo_state_path), repo_state_path,
          RepoState, 'JSONPB', test_proto=test_proto)
    else:
      repo_state = RepoState(
          state=(RepoState.STATE_DIRTY if self.m.path.exists(
              root_path.join('.repo')) else RepoState.STATE_CLEAN),
          manifest_branch=manifest_branch, manifest_url=manifest_url)

    # Output initial repo state
    self.m.easy.set_properties_step(
        initial_repo_state=MessageToDict(repo_state))

    # Add recovery fail
    if self._test_data.enabled and self._test_data.get('fail_repo_sync', False):
      repo_state.state = RepoState.STATE_RECOVERY

    if not self._disable_source_cache_health and repo_state.state == RepoState.STATE_RECOVERY:
      # Should only be reached if recovery error has occured.
      # Caller will delete the cache and start over.
      # Wrapped in feature flag
      return False

    # TODO(b/179259515): Ignore for now, adjust when tracking snapshot vs.ToT
    # if repo_state.manifest_branch != manifest_branch:
    #   # Raise step failure for inconsisten manifest_branch
    #   raise recipe_api.StepFailure(
    #       'manifest branch incorrect: expected {} got {}'.format(
    #           manifest_branch, repo_state.manifest_branch))

    # If the repo state is not STATE_CLEAN or the manifest_url has
    # changed then the checkout is considered dirty
    clean = (
        repo_state.state == RepoState.STATE_CLEAN and
        repo_state.manifest_url == manifest_url)

    # Set opt so we know if to clear locks or not during init()
    if init_opts:
      init_opts['clean'] = clean

    # Will update url them if they differ
    repo_state.manifest_url = manifest_url

    # Write current state to proto
    self.m.file.write_proto('Write proto to {}'.format(repo_state_path),
                            repo_state_path, repo_state, 'JSONPB')

    # Clean cache if needed
    self._sync_checkout(root_path, manifest_url, init_opts, sync_opts, projects,
                        clean)
    repo_state.state = RepoState.STATE_CLEAN

    self.m.file.write_proto('Write proto to {}'.format(repo_state_path),
                            repo_state_path, repo_state, 'JSONPB')
    return True

  def _sync_checkout(self, root_path, manifest_url, init_opts=None,
                     sync_opts=None, projects=None, clean=False):
    """Ensure the given repo checkout exists and is synced.

    Args:
      * root_path (Path): Path to the repo root.
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * projects (List[str]): Projects of concern or None if all projects
      are of concern. Used to perform optimizations where possible to only
      operate on the given projects.
    """
    with self.m.step.nest('ensure synced checkout'):
      self.m.file.ensure_directory('ensure root path', root_path)
      with self.m.context(cwd=root_path, infra_steps=True):
        init_opts = dict(init_opts or {}, projects=projects)
        sync_opts = dict(sync_opts or {}, projects=projects)
        manifest_name = init_opts.get('manifest_name')
        # The same value must be passed in both sets of options.
        assert manifest_name == sync_opts.get('manifest_name')
        if manifest_name:
          # Our API calls for manifest_name to be a Path, and the underlying
          # routines need manifest_name to be a string, giving the name of the
          # manifest relative to .repo/manifests. It must be inside of the
          # root_path.
          assert isinstance(manifest_name, Path)
          assert root_path.is_parent_of(manifest_name)
          init_opts['manifest_name'] = self.m.path.relpath(
              manifest_name, root_path.join('.repo/manifests'))
          sync_opts['manifest_name'] = self.m.path.relpath(
              manifest_name, root_path.join('.repo/manifests'))

        for retries in range(2):
          try:
            if not clean:
              # Remove .repo/manifests and .repo/manifests.git to avoid
              # potential problems when switching to a different manifest
              # repo or branch.
              for manifest_dir in ('manifests', 'manifests.git'):
                self.m.file.rmtree('remove .repo/%s' % manifest_dir,
                                   root_path.join('.repo', manifest_dir))

              self.init(manifest_url, **init_opts)
              self._git_clean_checkout(root_path, projects)
            else:
              self.init(manifest_url, **init_opts)
            self.sync(**sync_opts)
            break
          except recipe_api.StepFailure:
            if retries >= 1:
              raise
            self.m.step('sleep 10 min, try repo again', ['sleep', '600'])

      # Verify that root_path/.repo exists, since repo will happily reuse a
      # repository in the cwd's ancestor directories.
      assert self.m.path.exists(root_path.join('.repo')), '.repo not created!'

  def _binary_selfupdate(self, root_path):
    """Issues a repo selfupdate to update the binary.

    Args"
      * root_path (Path): Path to the repo root.
    """
    if self._binary_updated:
      return
    with self.m.step.nest('repo binary update'):
      self.version()
      with self.m.context(cwd=root_path, infra_steps=True):
        cmd = ['selfupdate']
        self._step(cmd, ok_ret='any')
      self.version()
      self._binary_updated = True
