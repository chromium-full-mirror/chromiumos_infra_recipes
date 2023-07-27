# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'repo' VCS tool.

See: https://chromium.googlesource.com/external/repo/
"""

from collections import defaultdict
from collections import namedtuple
import distutils.version  # pylint: disable=no-name-in-module
import json
import re
from typing import Any, Dict, List, Optional, Union
from xml.etree import cElementTree as ElementTree

from google.protobuf.json_format import MessageToDict
from PB.chromiumos.repo_cache_state import RepoState
from recipe_engine import recipe_api
from recipe_engine import step_data
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.git import api as git_api

MANIFEST_MOCK = '''
    <manifest>
      <project path="SAMPLE" revision="FROM_REV"/>
    </manifest>
  '''

ManifestDiff = namedtuple('ManifestDiff',
                          ['name', 'path', 'from_rev', 'to_rev'])


class ProjectInfo(
    namedtuple('ProjectInfo', ['name', 'path', 'remote', 'branch', 'rrev'])):

  __slots__ = ()

  @property
  def branch_name(self) -> str:
    """Return the branch name."""
    return (self.branch[len('refs/heads/'):]
            if self.branch.startswith('refs/heads/') else self.branch)


LocalManifest = namedtuple('LocalManifest', ['repo', 'path', 'branch'])


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  ManifestDiff = ManifestDiff
  ProjectInfo = ProjectInfo
  LocalManifest = LocalManifest

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._disable_source_cache_health = properties.disable_source_cache_health
    self._disable_repo_verify = properties.disable_repo_verify
    self._default_repo_url = properties.default_repo_url
    self._binary_updated = False
    self._repo_url = None
    self._repo_rev = None

    # Running stats variables for repo.
    # A list of dicts, key parameters from a repo sync operation log.
    self._all_syncs = []
    # A dictionary of repo 'name' to number of retries encountered.
    self._repo_retries = defaultdict(lambda: 0)

  def initialize(self) -> None:
    """Initialize the module after the recipe engine has been loaded."""
    self._disable_source_cache_health |= (
        'chromeos.repo.disable_source_cache_health' in
        self.m.cros_infra_config.experiments)

  @property
  def repo_path(self) -> Path:
    return self.m.depot_tools.repo_resource('repo')

  def _find_root(self) -> Optional[Path]:
    """Starting from cwd, find an ancestor with a '.repo' subdir."""
    candidate = self.m.context.cwd
    while candidate.pieces:
      if self.m.path.exists(candidate.join('.repo')):
        return candidate
      candidate = self.m.path.abs_to_path(self.m.path.dirname(candidate))
    return None

  def _step(self, args: List[str], name: Optional[str] = None,
            **kwargs) -> step_data.StepData:
    """Execute 'repo' with the supplied arguments.

    Args:
      args: A list of arguments to supply to 'repo'.
      name: The name of the step. If None, generate from the args.
      kwargs: See 'step.__call__'.

    Returns:
      Step data for the called command.
    """
    if name is None:
      name = 'repo'
      # Add first non-flag argument to name.
      for arg in args:
        if isinstance(arg, str) and arg[0] != '-':
          name = f'{name} {arg}'
          break
    kwargs.setdefault('infra_step', True)
    # Always run with depot_tools.on_path, since repo depends on it.
    with self.m.depot_tools.on_path():
      return self.m.step(name, [self.repo_path, *args], **kwargs)

  def _clear_git_locks(self, projects: Optional[List[str]] = None) -> None:
    """Remove git locks found in the repo checkout.

    Removes git locks in the repo checkout. The specifying of projects
    is provided as an optimization for applications that are dealing with
    a subset of the projects. The speedup can be substantial.

    Args:
      projects: Projects to limit the repo forall deleting of locks to, or None
        to clear all project locks.
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

  def version(self) -> str:
    """Get the version info retrieved by running `repo version`.

    Returns:
      The `repo` version as a numeric string, such as "2.39".
    """
    output = self._step(['version'], 'repo version', infra_step=True,
                        stdout=self.m.raw_io.output_text())
    match = re.match(r'repo version v([0-9.]+)', output.stdout)
    return match.group(1) if match else ''

  def version_at_least(self, version_string: str) -> bool:
    """Check to make sure repo version is as least the specified version.

    Args:
      version_string: the minimum version in format #.#(.#).

    Returns:
      True if the minimum version is satisfied, otherwise False.
    """
    with self.m.step.nest(
        f'check if repo version is at least {version_string}'):
      if current_version_string := self.version():
        # Note: distutils is deprecated and planned for removal in python3.12.
        # We should replace it with a suitable alternative.
        # https://docs.python.org/3/library/distutils.html
        min_version = distutils.version.LooseVersion(version_string)
        cur_version = distutils.version.LooseVersion(current_version_string)
        return cur_version >= min_version

    return False

  def init(self, manifest_url: str, *, manifest_branch: str = '',
           reference: Optional[str] = None, groups: Optional[List[str]] = None,
           depth: Optional[int] = None, repo_url: Optional[str] = None,
           repo_branch: Optional[str] = None,
           local_manifests: Optional[List[LocalManifest]] = None,
           manifest_name: Optional[Path] = None,
           projects: Optional[List[str]] = None, verbose: bool = True,
           clean: bool = True, manifest_depth: Optional[str] = None) -> None:
    """Execute 'repo init' with the given arguments.

    Args:
      manifest_url: URL of the manifest repository to clone.
      manifest_branch: Manifest repository branch to checkout.
      reference: Location of a mirror directory to bootstrap sync.
      groups: Groups to checkout (see `repo init --groups`).
      depth: Create a shallow clone of the given depth.
      repo_url: URL of the repo repository.
      repo_branch: Repo binary branch to use.
      local_manifests: Local manifests to add. See
        https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md#local-manifests.
      manifest_name: The manifest file to use.
      projects: Projects of concern or None if all projects are of concern.
        Ignored as of go/cros-source-cache-health.
      verbose: Whether to produce verbose output.
      manifest_depth: Value to pass in as manifest-depth to repo.
    """
    _ = projects
    cmd = ['init', '--manifest-url', manifest_url]
    if manifest_branch:
      cmd.extend(['--manifest-branch', manifest_branch])
    if reference is not None:
      cmd.extend(['--reference', reference])
    if groups is None:
      cmd.extend(['--groups', 'all'])
    else:
      assert not isinstance(groups, str)
      cmd.extend(['--groups', ','.join(groups)])
    if depth is not None:
      cmd.extend(['--depth', str(depth)])

    # If any caller in the recipe has specified repo_url or repo_branch, they
    # should be used for any subsequent call that does not explicitly specify
    # them.
    self._repo_url = repo_url or self._repo_url or self._default_repo_url
    self._repo_rev = repo_branch or self._repo_rev
    if not self._repo_rev and not self.m.cros_infra_config.is_staging:
      self._repo_rev = 'stable'

    if self._repo_url:
      cmd.append(f'--repo-url={self._repo_url}')
    if self._repo_rev:
      cmd.append(f'--repo-rev={self._repo_rev}')
    if self._disable_repo_verify:
      cmd.append('--no-repo-verify')
    if manifest_name:
      cmd.extend(['--manifest-name', manifest_name])
    if manifest_depth:
      cmd.extend(['--manifest-depth', manifest_depth])
    if verbose:
      cmd.append('--verbose')
    self._step(cmd, timeout=15 * 60)
    self._binary_selfupdate(self.m.context.cwd, not self._disable_repo_verify)
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
            local_manifest.repo, local_manifest.path,
            branch=local_manifest.branch or 'HEAD',
            step_test_data=self.test_api.local_manifest_step_test_data)
        self.m.file.write_raw(
            name='write local manifest',
            # If there is more than one local manifest, it needs a different
            # name.
            dest=local_manifest_dir.join(
                f'local_manifest_{i}.xml' if i else 'local_manifest.xml'),
            data=manifest_data,
        )

  def sync(self, *, force_sync: bool = False, detach: bool = False,
           current_branch: bool = False, jobs: Optional[int] = None,
           manifest_name: Optional[Path] = None, no_tags: bool = False,
           optimized_fetch: bool = False, cache_dir: Optional[Path] = None,
           timeout: Optional[int] = None, retry_fetches: Optional[int] = None,
           projects: Optional[List[str]] = None, verbose: bool = True,
           no_manifest_update: bool = False, force_remove_dirty: bool = False,
           prune: bool = None, repo_event_log: bool = True,
           manifest_branch_state: bool = True,
           test_manifest_branch_state_failure: bool = False) -> None:
    """Execute 'repo sync' with the given arguments.

    Args:
      force_sync: Overwrite existing git directories if needed.
      detach: Detach projects back to manifest revision.
      current_branch: Fetch only current branch.
      jobs: Projects to fetch simultaneously.
      manifest_name: Temporary manifest to use for this sync.
      no_tags: Don't fetch tags.
      optimized_fetch: Only fetch projects if revision doesn't exist.
      cache_dir: Use git-cache with this cache directory.
      timeout: Number of seconds before the recipe engine should kill the step.
      retry_fetches: The number of times to retry retryable fetches.
      projects: Projects to limit the sync to, or None to sync all projects.
      verbose: Whether to produce verbose output.
      no_manifest_update: Whether to disable updating the manifest.
      force_remove_dirty: Whether to force remove projects with uncommitted
        modifications if projects no longer exist in the manifest.
      prune: Delete refs that no longer exist on the remote.
      repo_event_log: Write the repo event log, do analysis steps.
      manifest_branch_state: Write `repo info` to stdout.
      test_manifest_branch_state_failure: Raise StepFailure in repo-info step
        and confirm it does not fail the entire build.
    """
    cmd = ['sync']
    if force_sync:
      cmd.append('--force-sync')
    if detach:
      cmd.append('--detach')
    if current_branch:
      cmd.append('--current-branch')
    if jobs:
      cmd.extend(['--jobs', str(jobs)])
    if manifest_name:
      cmd.extend(['--manifest-name', manifest_name])
    if no_tags:
      cmd.append('--no-tags')
    if optimized_fetch:
      cmd.append('--optimized-fetch')
    if cache_dir:
      cmd.extend(['--cache-dir', cache_dir])
    if retry_fetches:
      cmd.extend(['--retry-fetches', str(retry_fetches)])
    if verbose:
      cmd.append('--verbose')
    if no_manifest_update:
      cmd.append('--no-manifest-update')
    if force_remove_dirty:
      cmd.append('--force-remove-dirty')
    if repo_event_log:
      event_log_tmp = self.m.path.mkstemp('event_log_')
      cmd.insert(0, f'--event-log={event_log_tmp}')
    if prune is not None:
      if prune:
        cmd.append('--prune')
      else:
        cmd.append(['--no-prune'])  #pragma: nocover
    if projects:
      cmd.extend(projects)

    # Run repo sync. Capture failure and try to export stats, then reraise.
    step_exception = None
    try:
      self._step(cmd, name=None, timeout=timeout)
    except StepFailure as e:
      step_exception = e
    finally:
      if repo_event_log:
        with self.m.step.nest('repo stats') as pres:
          try:
            if event_log_tmp:
              event_log_text = self.m.file.read_text(
                  'event-log', event_log_tmp,
                  test_data=self.test_api.repo_event_log_text())
              pres.logs['repo-event-log'] = event_log_text
              self._export_sync_stats(event_log_text)
          except StepFailure as e:
            # Failure on this should not stop the build.
            pres.status = self.m.step.WARNING
            pres.step_text = f'failure reading repo request logs {e}'
      if manifest_branch_state:
        with self.m.step.nest('repo info') as pres:
          try:
            pres.logs['repo-info stdout'] = self.report_manifest_branch_state(
                projects=projects,
                test_failure=test_manifest_branch_state_failure)
          except StepFailure as e:
            # Don't fail the builder on issues reporting manifest branch state.
            pres.status = self.m.step.INFRA_FAILURE
            pres.step_text = f'failure reporting manifest branch state {e}'
      if step_exception:
        # We're certain that this is an Exception.
        raise step_exception  #pylint: disable=raising-bad-type

  def _export_sync_stats(self, repo_event_log_text: str) -> None:
    """Process the repo event log into builder properties.

    Updates and outputs statisics information gathered from the repo event log.
    The stats include the slowest repos, as well as the number of retries the
    builder made during its execution. It updates class level locals if repo is
    called muliple times.

    We should catch exceptions here and not interrupt builders if we fail.

    Args:
      repo_event_log_text: A repo event log string, jsonl format.
    """
    try:
      syncs = []
      repo_dicts = []
      update_retries = False
      for line in repo_event_log_text.splitlines():
        repo_dicts.append(json.loads(line))

      for repo_dict in repo_dicts:
        if repo_dict['task_name'] == 'sync-network':
          this_sync = {}

          this_sync['name'] = repo_dict['name']
          for s in ['project', 'project_url', 'revision', 'status']:
            if s in repo_dict:
              this_sync[s] = repo_dict[s]

          # Find time span.
          this_sync['time_delta_sec'] = float(repo_dict['finish_time']) - float(
              repo_dict['start_time'])

          # Incorporate new retries.
          tries = int(repo_dict['try'])
          this_sync['try'] = tries
          if this_sync['status'] == 'pass' and tries > 1:
            update_retries = True
            self._repo_retries['project'] += (tries - 1)

          syncs.append(this_sync)

      if update_retries:
        self.m.easy.set_properties_step(repo_retries=self._repo_retries)

      # Integrate this repo's run into the slowest repos list.
      self._all_syncs = sorted(syncs + self._all_syncs,
                               key=lambda x: x['time_delta_sec'], reverse=True)
      slowest_repos = {}
      for i, repo_dict in enumerate(self._all_syncs[:5]):
        slowest_repos[str(i)] = repo_dict
      self.m.easy.set_properties_step(slowest_repos=slowest_repos)

    except (KeyError, TypeError, ValueError) as e:
      raise StepFailure(e) from e

  def create_tmp_manifest(self, manifest_data: str) -> Path:
    """Write manifest_data to a temporary manifest file inside the repo root.

    Args:
      manifest_data: The contents to write into the new manifest file.

    Returns:
      Path to the new manifest file.
    """
    repo_root = self._find_root()
    if repo_root is None:
      raise recipe_api.StepFailure('no repo root found')

    manifest_path = repo_root.join('.repo', 'tmp_manifest')
    self.m.file.write_raw('write manifest', manifest_path, manifest_data)

    return manifest_path

  def sync_manifest(self, manifest_url: str, manifest_data: str,
                    **kwargs) -> None:
    """Sync to the given manifest file data.

    Args:
      manifest_url: URL of manifest repo to sync to (for repo init)
      manifest_data: Manifest XML data to use for the sync.
      kwargs: Keyword arguments to pass to 'repo.sync'.
    """
    repo_root = self._find_root()
    assert repo_root is not None, 'no repo root found'

    repo_manifests_path = repo_root.join('.repo', 'manifests')
    manifest_path = self.create_tmp_manifest(manifest_data)
    manifest_relpath = self.m.path.relpath(manifest_path, repo_manifests_path)

    init_opts = {'projects': kwargs.get('projects', None)}
    self.init(manifest_url, manifest_name=manifest_relpath, manifest_depth='0',
              **init_opts)
    self.sync(**kwargs)

  def start(self, branch: str, projects: Optional[List[str]] = None) -> None:
    """Start a new branch in the given projects, or all projects if not set.

    Args:
      branch: The new branch name.
      projects: The projects for which to start a branch.
    """
    cmd = ['start', branch]
    if projects is not None:
      cmd.extend(projects)
    else:
      cmd.append('--all')
    self._step(cmd)

  def abandon(self, branch: str, projects: Optional[List[str]] = None) -> None:
    """Abandon the branch in the given projects, or all projects if not set.

    Args:
      branch: The branch to abandon.
      projects: The projects for which to abandon the branch.
    """
    cmd = ['abandon', branch]
    if projects is not None:
      cmd.extend(projects)
    else:
      cmd.append('--all')
    self._step(cmd)

  def project_infos(self, projects: Optional[List[str]] = None,
                    regexes: Optional[List[str]] = None,
                    test_data: Optional[str] = None,
                    ignore_missing: bool = False) -> List[ProjectInfo]:
    """Use 'repo forall' to gather project information.

    Note that if both projects and regexes are specified the resultant
    ProjectInfos are the union, without duplicates, of what each would
    return separately.

    Note that this doesn't guarantee that the return value has no duplicates.
    The caller will need to handle that themselves.

    Args:
      projects: Project names or paths to return info for. Defaults to all
        projects.
      regexes: List of regexes for matching projects. The matching is the same
        as in `repo forall --regex regexes...`.
      test_data: Test data for the step: the output from repo forall, or None
        for the default.
      ignore_missing: If True, skip missing projects and continue.

    Returns:
      Requested project infos.
    """
    if test_data is None:
      test_data = self.test_api.project_infos_test_data([{
          'project': p
      } for p in (projects or self.test_api.test_projects)])
    step_test_data = lambda: self.m.raw_io.test_api.stream_output_text(test_data
                                                                      )

    cmd = ['forall', '-v']
    cmd.extend(['--ignore-missing'] if ignore_missing else [])
    cmd.extend(['--regex', *regexes] if regexes else [])
    cmd.extend(projects if projects else [])
    cmd.extend([
        '-c', r'echo $REPO_PROJECT\|$REPO_PATH\|$REPO_REMOTE\|$REPO_RREV\|'
        r'$REPO_UPSTREAM'
    ])
    repo_step_data = self._step(
        cmd, stdout=self.m.raw_io.output_text(add_output_log=True),
        step_test_data=step_test_data)

    infos = []
    lines = repo_step_data.stdout.strip().split('\n')

    # If nothing was matched, return the empty infos.
    if lines == ['']:
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

  def project_info(self, project: Optional[Union[str, Path]] = None,
                   **kwargs: Dict[str, Any]) -> 'ProjectInfo':
    """Use 'repo forall' to gather project information for one project.

    Args:
      project: Project name or path to return info for. If None, then use the
        cwd as the path for the project.
      kwargs: Additional keyword arguments to pass into self.project_infos.

    Returns:
      ProjectInfo: The request project info.
    """
    project = project or self.m.context.cwd
    project_infos = self.project_infos(projects=[project], **kwargs)
    assert len(set(project_infos)) == 1, 'expected one project'
    return project_infos[0]

  def project_exists(self, project: str) -> bool:
    """Use 'repo info' to determine if the project exists in the checkout.

    Args:
      project: Project name or path to check for.

    Returns:
      Whether or not the project exists.
    """
    with self.m.step.nest(f'check if project {project} exists'):
      cmd = ['info', project]
      repo_step_data = self._step(
          cmd,
          stderr=self.m.raw_io.output_text(add_output_log=True),
          ok_ret=[0, 1],
      )

      # Consider a project found iff the string 'project {project} not found' is
      # not in the stderr.
      #
      # Note that `repo info` will return 0 as an exit code even if the project
      # is not found, so we don't use this to determine if it is found. Also,
      # `repo info` may return non-empty stderr if the project is found, so we
      # also don't use this to determine if it is found.
      # TODO(b/272513582): Use something more robust, such as `repo forall`.
      errmsg = f'project {project} not found'
      return errmsg not in repo_step_data.stderr

  def report_manifest_branch_state(self, projects: Optional[List[str]] = None,
                                   test_data: str = 'Repo: info',
                                   test_failure: bool = False) -> str:
    """Use 'repo info' to output manifest state to stdout.
    Args:
      projects: Projects to limit the info call to, or None to get info for all
        projects.
      test_data: Optional data for testing stdout.
      test_failure: Raise StepFailure or not

    Returns:
      Full info on the manifest branch, current branch or unmerged branches.
    """
    if test_failure:
      raise StepFailure('tested failure in repo-info step')
    cmd = [self.repo_path, 'info']
    if projects:
      cmd.extend(projects)
    stdout = self.m.easy.stdout_step('repo info', cmd,
                                     test_stdout=lambda: test_data)
    return stdout.decode().strip()

  def ensure_pinned_manifest(self, projects: Optional[List[str]] = None,
                             regexes: Optional[List[str]] = None,
                             test_data: Optional[str] = None) -> Optional[str]:
    """Ensure that we know the revision info for all projects.

    If the manifest is not pinned, a pinned manifest is created and logged.

    Args:
      projects: Project names or paths to return info for. Defaults to all
        projects.
      regexes: list of regexes for matching projects. The matching is the same
        as in `repo forall --regex regexes...`.
      test_data: Test data for the step: the output from repo forall, or None
        for the default. This is passed to project_infos().

    Returns:
      The manifest XML as a string, or None if the manifest is already pinned.
    """
    with self.m.step.nest('ensure manifest is pinned') as pres:
      infos = self.project_infos(projects=projects, regexes=regexes,
                                 test_data=test_data)
      if not all(re.match(r'[0-9a-fA-F]{40}$', x.rrev) for x in infos):
        manifest = self.manifest(pinned=True)
        pres.logs['pinned-manifest.xml'] = manifest
        return manifest
      return None

  def manifest(self, manifest_file: Optional[Path] = None,
               test_data: Optional[str] = None, pinned: bool = False,
               step_name=None) -> str:
    """Use repo to create a manifest and returns it as a string.

    By default uses the internal .repo manifest, but can optionally take
    another manifest to use.

    Args:
      manifest_file: If given, path to alternate manifest file to use.
      test_data: Test data for the step: the contents of the manifest, or None
        for the default.
      pinned: Whether to create a pinned (snapshot) manifest.
      step_name: The name for the step, or None to use a default.

    Returns:
      str: The manifest XML as a string.
    """
    step_test_data = lambda: self.m.raw_io.test_api.stream_output_text(
        test_data or '<manifest></manifest>')

    cmd = ['manifest']
    if pinned:
      cmd.append('-r')
    if manifest_file:
      cmd.extend(['-m', manifest_file])

    repo_step_data = self._step(
        cmd, stdout=self.m.raw_io.output_text(add_output_log=True),
        step_test_data=step_test_data, name=step_name)
    return repo_step_data.stdout.strip()

  def diff_remote_and_local_manifests(
      self, from_manifest_url: str, from_manifest_ref: str,
      to_manifest_str: str, test_from_data: Optional[str] = None,
      use_merge_base: bool = False) -> List[ManifestDiff]:
    """Diff the remote manifest against the local manifest string.

    Diffs the 'snapshot.xml' at the given `from_manifest_url` at the ref
    `from_manifest_ref` against the local `to_manifest_str`.

    Args:
      from_manifest_url: The manifest repo url to checkout.
      from_manifest_ref: The manifest ref to checkout.
      to_manifest_str: The string XML for the to manifest.
      test_from_data: Test data: The from_manifest contents, or None for the
        default.
      use_merge_base: Whether to adjust the from_ref with `git merge-base`.

    Returns:
      An array of `ManifestDiff` namedtuples for any existing changed project
      (excludes added/removed projects).
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

  def diff_manifests(self, from_manifest_str: str, to_manifest_str: str,
                     use_merge_base: bool = False) -> List[ManifestDiff]:
    """Diff the two manifests and returns an array of differences.

    Given the two manifest XML strings, generates an array of `ManifestDiff`.
    This only returns **CHANGED** projects, it skips over projects that were
    added or deleted.

    Args:
      from_manifest_str: The manifest XML string to diff from.
      to_manifest_str: The manifest XML string to diff against.
      use_merge_base: Whether to adjust the from_ref with `git merge-base`.

    Returns:
      An array of `ManifestDiff` namedtuple for any existing changed project
      (excludes added/removed projects).
    """
    _test_data_default_remote = 'cros'

    def snapshot_mode(project: ElementTree) -> Optional[str]:
      """Find and return the snapshot-mode annotation from the project XML."""
      for annotation in project.iterfind('annotation'):
        if annotation.get('name') == 'snapshot-mode':
          return annotation.get('value')
      return None

    def find_default_remote(xml_data: str) -> List[str]:
      """Find and return the default remote from the XML data."""
      xml = ElementTree.fromstring(xml_data)
      ret = [
          x.attrib.get('remote')
          for x in xml.iterfind('default')
          if x.attrib.get('remote')
      ] + [_test_data_default_remote]
      return ret[0]

    def find_remotes(xml_data: str) -> Dict[str, str]:
      """Find and return all remotes by name in the XML data."""
      xml = ElementTree.fromstring(xml_data)
      remotes = [x.attrib for x in xml.iterfind('remote')] or [{
          'name': _test_data_default_remote
      }]
      for remote in remotes:
        remote.setdefault('alias', remote.get('name'))
      return {remote['name']: remote for remote in remotes}

    def project_paths(xml_data: str) -> Dict[str, str]:
      """Find and return all project paths and their attrs from the XML data."""
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
        with self.m.step.nest(f'validate {from_path}') as val_pres, \
            self.m.context(cwd=repo_root.join(from_path)):
          # The git helper binary does retries of its own, so we do not need to.
          if not self.m.git.is_reachable(from_revision, to_revision):
            try:
              self.m.git.fetch(from_remote, [from_revision], retries=0)
            except recipe_api.StepFailure:
              # Changes in the manifest project/branch may mean that the
              # from_revision is not an ancestor of the to_revision.  If history
              # was rewritten, it may not even exist any more.
              pass
          # If the from_revision is unreachable, ignore changes for the project.
          base = self.m.git.merge_base(from_revision, to_revision,
                                       test_stdout=from_revision) or to_revision
          val_pres.step_text = (
              from_revision
              if from_revision == base else f'{from_revision} => {base}')
          from_revision = base
      changes.append(
          ManifestDiff(from_name, from_path, from_revision, to_revision))
    return changes

  def diff_manifests_informational(self, old_manifest_path: Path,
                                   new_manifest_path: Path) -> None:
    """Informational step that logs a "manifest diff".

    Args:
      old_manifest_path: Path to old manifest file.
      new_manifest_path: Path to new manifest file.
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

  def _git_sanitize_checkout(self, root_path: Path,
                             projects: Optional[List[str]] = None) -> None:
    """Execute cleaning operations to minimize git tree size & check integrity.

    Args:
      root_path: Path to the repo root.
      projects: Projects to clean or None to clean all projects.
    """
    with self.m.step.nest('ensure sanitized checkout'), self.m.context(
        cwd=root_path, infra_steps=True):
      cmd = ['forall'] + (projects or [])
      gc_args = ['--ignore-missing', '-j', '32', '-c', 'git', 'gc']
      try:
        self._step(cmd + gc_args,
                   stdout=self.m.raw_io.output_text(add_output_log=True),
                   ok_ret='any')
      except recipe_api.StepFailure:  # pragma: nocover
        self.m.step.active_result.presentation.status = self.m.step.WARNING

  def _git_clean_checkout(self, root_path: Path,
                          projects: Optional[List[str]] = None) -> None:
    """Ensure the given repo does not contain untracked files or directories.

    We're assuming that the root path provided has already been validated.

    Args:
      root_path: Path to the repo root.
      projects: Projects to clean or None to clean all projects.
    """
    with self.m.step.nest('ensure clean checkout'), self.m.context(
        cwd=root_path, infra_steps=True):
      cmd = ['forall'] + (projects or [])
      reset_args = [
          '--ignore-missing', '-j', '32', '-c', 'git', 'reset', '--hard'
      ]
      try:
        self._step(cmd + reset_args,
                   stdout=self.m.raw_io.output_text(add_output_log=True),
                   ok_ret='any')
      except recipe_api.StepFailure:  # pragma: nocover
        self.m.step.active_result.presentation.status = self.m.step.WARNING
        self._step(['forall'] + reset_args, 'retry git reset')

      clean_args = [
          '--ignore-missing', '-j', '32', '-c', 'git', 'clean', '-x', '-d', '-f'
      ]
      try:
        self._step(cmd + clean_args,
                   stdout=self.m.raw_io.output_text(add_output_log=True),
                   ok_ret='any')
      except recipe_api.StepFailure:  # pragma: nocover
        self.m.step.active_result.presentation.status = self.m.step.WARNING
        self._step(['forall'] + clean_args, 'retry clear git locks')

  @property
  def manifest_gitiles_commit(self) -> git_api.GitilesCommit:
    """Return a Gitiles commit for the repo manifest."""
    with self.m.context(cwd=self._find_root().join('.repo', 'manifests')):
      return self.m.git.gitiles_commit()

  def ensure_synced_checkout(self, root_path: Path, manifest_url: str,
                             init_opts: Optional[Dict[str, Any]] = None,
                             sync_opts: Optional[Dict[str, Any]] = None,
                             projects: Optional[List[str]] = None,
                             final_cleanup: bool = False,
                             sanitize: bool = False) -> bool:
    """Ensure the given repo checkout exists and is synced.

    Args:
      root_path: Path to the repo root.
      manifest_url: Manifest URL for 'repo.init`.
      init_opts: Extra keyword arguments to pass to 'repo.init'.
      sync_opts: Extra keyword arguments to pass to 'repo.sync'.
      projects: Projects of concern or None if all projects are of concern. Used
        to perform optimizations where possible to only operate on the given
        projects.
      final_cleanup: Used by cache builder to ensure that all locks and
        uncommitted files are cleaned up after the sync.
      sanitize: Whether to run `git gc` on all repos.

    Returns:
      Whether the sync succeeded.
    """
    repo_state_path = root_path.join('.recipes_state.json')
    manifest_branch = init_opts.get('manifest_branch', '') if init_opts else ''
    # Get cache state
    if self.m.path.exists(repo_state_path) and not final_cleanup:
      test_proto = None
      if self._test_data.enabled:
        test_proto = RepoState(
            state=self._test_data.get('repo_current_state',
                                      RepoState.STATE_DIRTY),
            manifest_branch=self._test_data.get('repo_manifest_branch',
                                                manifest_branch),
            manifest_url=manifest_url,
        )
      repo_state = self.m.file.read_proto(f'Read proto from {repo_state_path}',
                                          repo_state_path, RepoState, 'JSONPB',
                                          test_proto=test_proto)
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

    if (not self._disable_source_cache_health and
        repo_state.state == RepoState.STATE_RECOVERY):
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

    clean = (repo_state.state == RepoState.STATE_CLEAN)

    # Set opt so we know if to clear locks or not during init()
    if init_opts:
      init_opts['clean'] = clean

    # Will update url them if they differ
    repo_state.manifest_url = manifest_url

    # Write current state to proto
    self.m.file.write_proto(f'Write proto to {repo_state_path}',
                            repo_state_path, repo_state, 'JSONPB')

    # If we're sanitizing the repo do this before the sync.
    if sanitize:
      self._git_sanitize_checkout(root_path, projects=projects)

    # Clean cache if needed
    self._sync_checkout(root_path, manifest_url, init_opts=init_opts,
                        sync_opts=sync_opts, projects=projects, clean=clean,
                        final_cleanup=final_cleanup)
    repo_state.state = RepoState.STATE_CLEAN

    self.m.file.write_proto(f'Write proto to {repo_state_path}',
                            repo_state_path, repo_state, 'JSONPB')
    return True

  def _sync_checkout(self, root_path: Path, manifest_url: str,
                     init_opts: Dict[str,
                                     Any] = None, sync_opts: Dict[str,
                                                                  Any] = None,
                     projects: Optional[List[str]] = None, clean: bool = False,
                     final_cleanup: bool = False) -> None:
    """Ensure the given repo checkout exists and is synced.

    Args:
      root_path: Path to the repo root.
      manifest_url: Manifest URL for 'repo.init`.
      init_opts: Extra keyword arguments to pass to 'repo.init'.
      sync_opts: Extra keyword arguments to pass to 'repo.sync'.
      projects: Projects of concern or None if all projects are of concern. Used
        to perform optimizations where possible to only operate on the given
        projects.
      clean: Whether the cache is clean.
      final_cleanup: Boolean stating whether to perform a final cleanup after
        the sync.
    """
    with self.m.step.nest('ensure synced checkout') as presentation:
      self.m.file.ensure_directory('ensure root path', root_path)
      with self.m.context(cwd=root_path, infra_steps=True):
        init_opts = init_opts or {}
        init_opts['projects'] = projects
        sync_opts = sync_opts or {}
        sync_opts['projects'] = projects
        manifest_name = init_opts.get('manifest_name')
        # The same value must be passed in both sets of options.
        assert manifest_name == sync_opts.get('manifest_name')
        # Manifest branch must be passed with init_opts
        assert 'manifest_branch' in init_opts, (
            'manifest tracking branch not specified.')
        branch = init_opts['manifest_branch']
        presentation.step_text = f'cache tracking "{branch}" branch'
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
            self.init(manifest_url, **init_opts)
            if not clean:
              self._git_clean_checkout(root_path, projects)
            self.sync(**sync_opts)
            break
          except recipe_api.StepFailure:
            if retries >= 1:
              raise
            self.m.step('sleep 10 min, try repo again', ['sleep', '600'])
            clean = False
        if final_cleanup:
          self._git_clean_checkout(root_path, projects)

      # Verify that root_path/.repo exists, since repo will happily reuse a
      # repository in the cwd's ancestor directories.
      assert self.m.path.exists(root_path.join('.repo')), '.repo not created!'

  def _binary_selfupdate(self, root_path: Path, verify_repo: bool) -> None:
    """Issue a repo selfupdate to update the binary.

    Args:
      root_path: Path to the repo root.
      verify_repo: Whether to verify the signature on repo.
    """
    if self._binary_updated:
      return
    with self.m.step.nest('repo binary update'):
      self.version()
      # When repo updates to the next version, the `.repo/repo` project
      # sometimes gets stuck with local changes that prevent selfupdate.
      # This error  presents as: "could not reset index file to revision".
      # `git checkout --force` fixes this by clobbering local changes to the
      # `.repo/repo` project.
      # See b/243418745 for more info.
      if root_path:
        with self.m.context(
            cwd=root_path.join('.repo', 'repo'), infra_steps=True):
          self.m.git.checkout(force=True)
      with self.m.context(cwd=root_path, infra_steps=True):
        cmd = ['selfupdate']
        if not verify_repo:
          cmd.append('--no-repo-verify')
        try:
          self._step(cmd, ok_ret={0})
        except recipe_api.StepFailure:
          # TODO(b/221862521): Remove this when bug is resolved.
          # `repo selfupdate` is known to be broken.
          # It succeeds in updating repo, but fails to re-exec itself.
          # Subsequent calls to `repo selfupdate` in a build will pass
          # because `repo` will show the most up-to-date version, so the call
          # will noop and thus avoid the broken codepath.
          self._step(cmd, ok_ret={0})
      self.version()
      self._binary_updated = True
