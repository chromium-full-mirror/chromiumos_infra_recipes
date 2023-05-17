# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'repo' VCS tool.

See: https://chromium.googlesource.com/external/repo/
"""

from collections import defaultdict
from collections import namedtuple
import distutils.version
import json
import re
from xml.etree import cElementTree as ElementTree

from google.protobuf.json_format import MessageToDict
from PB.chromiumos.repo_cache_state import RepoState
from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import StepFailure

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


LocalManifest = namedtuple('LocalManifest', ['repo', 'path', 'branch'])


class RepoApi(recipe_api.RecipeApi):
  """A module for interacting with the repo tool."""

  ManifestDiff = ManifestDiff
  ProjectInfo = ProjectInfo
  LocalManifest = LocalManifest

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._disable_source_cache_health = properties.disable_source_cache_health
    self._remove_manifests_git = properties.remove_manifests_git
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

  def initialize(self):
    self._disable_source_cache_health |= (
        'chromeos.repo.disable_source_cache_health' in
        self.m.cros_infra_config.experiments)
    self._remove_manifests_git |= ('chromeos.repo.remove_manifests_git' in
                                   self.m.cros_infra_config.experiments)

  @property
  def repo_path(self):
    return self.m.depot_tools.repo_resource('repo')

  @property
  def disable_source_cache_health(self):
    return self._disable_source_cache_health

  def _find_root(self):
    """Starting from cwd, find an ancestor with a '.repo' subdir."""
    candidate = self.m.context.cwd
    while candidate.pieces:
      if self.m.path.exists(candidate.join('.repo')):
        return candidate
      candidate = self.m.path.abs_to_path(self.m.path.dirname(candidate))
    return None

  def _step(self, args, name=None, **kwargs):
    """Executes 'repo' with the supplied arguments.

    Args:
      args (list): A list of arguments to supply to 'repo'.
      name (str): The name of the step. If None, generate from the args.
      kwargs: See 'step.__call__'.

    Returns:
      StepData: See 'step.__call__'.
    """
    if name is None:
      name = 'repo'
      # Add first non-flag argument to name.
      for arg in args:
        if isinstance(arg, str) and arg[:1] != '-':
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
      projects (list[str]): Projects to limit the repo forall deleting of
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

  def version(self, return_version=False):
    """Gets the version info retrieved by running `repo version`.

    Args:
      return_version (bool): If true, return just the parsed version. If false,
        emit the full version command text into the step's stdout.
    """
    output = self._step(
        ['version'], 'repo version', infra_step=True,
        stdout=self.m.raw_io.output_text() if return_version else None)
    if return_version:
      match = re.match(r'repo version v([0-9.]+)', output.stdout)
      return match.group(1) if match else ''
    return output

  def version_at_least(self, version_string):
    """Checks to make sure repo version is as least the specified version.

    Args:
      version_string (str): the minimum version in format #.#(.#).

    Returns:
      True if the minimum version is satisfied, otherwise False.
    """
    with self.m.step.nest(
        'check if repo version is at least {}'.format(version_string)):
      current_version_string = self.version(return_version=True)
      if current_version_string:
        # Note: distutils is slated for deprecation in python 3.12. We should
        # explore replacing this with a suitable alternative, which will be made
        # easier when we're off python 2. See b/197782701.
        min_version = distutils.version.LooseVersion(version_string)
        cur_version = distutils.version.LooseVersion(current_version_string)
        return cur_version >= min_version

    return False

  def init(self, manifest_url, *, manifest_branch='', reference=None,
           groups=None, depth=None, repo_url=None, repo_branch=None,
           local_manifests=None, manifest_name=None, projects=None,
           verbose=True, clean=True, manifest_depth=None):
    """Executes 'repo init' with the given arguments.

    Args:
      manifest_url (str): URL of the manifest repository to clone.
      manifest_branch (str): Manifest repository branch to checkout.
      reference (str): Location of a mirror directory to bootstrap sync.
      groups (list): Groups to checkout (see `repo init --groups`).
      depth (int): Create a shallow clone of the given depth.
      repo_url (str): URL of the repo repository.
      repo_branch (str): Repo binary branch to use.
      local_manifests (list[LocalManifest]): Local manifests to add. See
        https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md#local-manifests.
      manifest_name (Path): The manifest file to use.
      projects (list[str]): Projects of concern or None if all projects are of
        concern. Ignored as of go/cros-source-cache-health.
      verbose (bool): Whether to produce verbose output.
      manifest_depth (str): Value to pass in as manifest-depth to repo.
    """
    _ = projects
    verify_repo = not self._disable_repo_verify
    cmd = ['init', '--manifest-url', manifest_url, '--groups', 'all']
    if manifest_branch:
      cmd += ['--manifest-branch', manifest_branch]
    if reference is not None:
      cmd += ['--reference', reference]
    if groups is not None:
      assert not isinstance(groups, str)
      cmd += ['--groups', ','.join(groups)]
    if depth is not None:
      cmd += ['--depth', '%d' % depth]

    # If any caller in the recipe has specified repo_url or repo_branch, they
    # should be used for any subsequent call that does not explicitly specify
    # them.
    self._repo_url = repo_url or self._repo_url or self._default_repo_url
    self._repo_rev = repo_branch or self._repo_rev
    if not self._repo_rev and not self.m.cros_infra_config.is_staging:
      self._repo_rev = 'stable'

    if self._repo_url:
      cmd += ['--repo-url=%s' % self._repo_url]
    if self._repo_rev:
      cmd += ['--repo-rev=%s' % self._repo_rev]
    if not verify_repo:
      cmd += ['--no-repo-verify']
    if manifest_name:
      cmd += ['--manifest-name', manifest_name]
    if manifest_depth:
      cmd += ['--manifest-depth', manifest_depth]
    if verbose:
      cmd += ['--verbose']
    self._step(cmd, timeout=15 * 60)
    self._binary_selfupdate(self.m.context.cwd, verify_repo)
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
            dest=local_manifest_dir.join('local_manifest_{}.xml'.format(i)
                                         if i else 'local_manifest.xml'),
            data=manifest_data,
        )

  def sync(self, *, force_sync=False, detach=False, current_branch=False,
           jobs=None, manifest_name=None, no_tags=False, optimized_fetch=False,
           cache_dir=None, timeout=None, retry_fetches=None, projects=None,
           verbose=True, no_manifest_update=False, force_remove_dirty=False,
           prune=None, repo_event_log=True, manifest_branch_state=True,
           test_manifest_branch_state_failure=False):
    """Executes 'repo sync' with the given arguments.

    Args:
      force_sync (bool): Overwrite existing git directories if needed.
      detach (bool): Detach projects back to manifest revision.
      current_branch (bool): Fetch only current branch.
      jobs (int): Projects to fetch simultaneously.
      manifest_name (str): Temporary manifest to use for this sync.
      no_tags (bool): Don't fetch tags.
      optimized_fetch (bool): Only fetch projects if revision doesn't exist.
      cache_dir (Path): Use git-cache with this cache directory.
      retry_fetches (int): The number of times to retry retriable fetches.
      projects (list[str]): Projects to limit the sync to, or None to sync
        all projects.
      verbose (bool): Whether to produce verbose output.
      no_manifest_update (bool): Whether to disable updating the manifest.
      force_remove_dirty (bool): Whether to force remove projects with
        uncommitted modifications if projects no longer exist in the manifest.
      prune (bool): Delete refs that no longer exist on the remote.
      repo_event_log (bool): Write the repo event log, do analysis steps.
      manifest_branch_state (bool): Write `repo info` to stdout.
      test_manifest_branch_state_failure (bool): Raise StepFailure in repo-info
      step and confirm it does not fail the entire build.
    """
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
    if verbose:
      cmd += ['--verbose']
    if no_manifest_update:
      cmd += ['--no-manifest-update']
    if force_remove_dirty:
      cmd += ['--force-remove-dirty']
    if repo_event_log:
      event_log_tmp = self.m.path.mkstemp('event_log_')
      cmd = ['--event-log={}'.format(event_log_tmp)] + cmd
    if prune is not None:
      if prune:
        cmd += ['--prune']
      else:
        cmd += ['--no-prune']  #pragma: nocover
    if projects:
      cmd += projects

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
            pres.step_text = 'failure reading repo request logs {}'.format(e)
      if manifest_branch_state:
        with self.m.step.nest('repo info') as pres:
          try:
            pres.logs['repo-info stdout'] = self.report_manifest_branch_state(
                projects=projects,
                test_failure=test_manifest_branch_state_failure)
          except StepFailure as e:
            # Don't fail the builder on issues reporting manifest branch state.
            pres.status = self.m.step.INFRA_FAILURE
            pres.step_text = 'failure reporting manifest branch state {}'.format(
                e)
      if step_exception:
        # We're certain that this is an Exception.
        raise step_exception  #pylint: disable=raising-bad-type

  def _export_sync_stats(self, repo_event_log_text):
    """Process the repo event log into builder properties.

    Updates and outputs statisics information gathered from the repo event log.
    The stats include the slowest repos, as well as the number of retries the
    builder made during its execution. It updates class level locals if repo is
    called muliple times.

    We should catch exceptions here and not interrupt builders if we fail.

    Args:
      repo_event_log_text (str): A repo event log string, jsonl format.
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

  def create_tmp_manifest(self, manifest_data):
    """Write manifest_data to a temporary manifest file inside the repo root.

    Returns (string): path of tmp manifest relative.
    """
    repo_root = self._find_root()
    if repo_root is None:
      raise recipe_api.StepFailure('no repo root found')

    manifest_path = repo_root.join('.repo', 'tmp_manifest')
    self.m.file.write_raw('write manifest', manifest_path, manifest_data)

    return manifest_path

  def sync_manifest(self, manifest_url, manifest_data, **kwargs):
    """Sync to the given manifest file data.

    Args:
      manifest_url (str): URL of manifest repo to sync to (for repo init)
      manifest_data (str): Manifest XML data to use for the sync.
      kwargs: Keyword arguments to pass to 'repo.sync'.
    """
    repo_root = self._find_root()
    assert repo_root is not None, 'no repo root found'

    repo_manifests_path = repo_root.join('.repo', 'manifests')
    manifest_path = self.create_tmp_manifest(manifest_data)
    manifest_relpath = self.m.path.relpath(manifest_path, repo_manifests_path)

    init_opts = {"projects": kwargs.get("projects", None)}
    self.init(manifest_url, manifest_name=manifest_relpath, manifest_depth='0',
              **init_opts)
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

  def project_infos(self, projects=None, regexes=None, test_data=None,
                    ignore_missing=False):
    """Uses 'repo forall' to gather project information.

    Note that if both projects and regexes are specified the resultant
    ProjectInfos are the union, without duplicates, of what each would
    return separately.

    Note that this doesn't guarantee that the return value has no duplicates.
    The caller will need to handle that themselves.

    Args:
      projects (list[str]): Project names or paths to return info for. Defaults
        to all projects.
      regexes (list[str]): list of regexes for matching projects. The matching
        is the same as in `repo forall --regex regexes...`.
      test_data (str): Test data for the step: the output from repo forall, or
          None for the default.
      ignore_missing (bool): If True, skip missing projects and continue

    Returns:
      list[ProjectInfo]: Requested project infos.
    """
    if test_data is None:
      test_data = self.test_api.project_infos_test_data(
          [dict(project=p) for p in projects or self.test_api.test_projects])
    step_test_data = lambda: self.m.raw_io.test_api.stream_output_text(test_data
                                                                      )

    cmd = []
    cmd += ['forall']
    cmd += ['--ignore-missing'] if ignore_missing else []
    cmd += (['--regex'] + regexes) if regexes is not None else []
    cmd += projects if projects is not None else []
    cmd += [
        '-c', r'echo $REPO_PROJECT\|$REPO_PATH\|$REPO_REMOTE\|$REPO_RREV\|'
        r'$REPO_UPSTREAM'
    ]
    step_data = self._step(
        cmd, stdout=self.m.raw_io.output_text(add_output_log=True),
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

  def project_exists(self, project):
    """Use 'repo info' to determine if the project exists in the checkout.

    Args:
      project (str): Project name or path to return info for.

    Returns:
      (bool): whether or not the project exists.
    """
    with self.m.step.nest('check if project {} exists'.format(project)):
      cmd = ['info', project]
      step_data = self._step(
          cmd, stderr=self.m.raw_io.output_text(add_output_log=True),
          ok_ret=[0, 1])

      stderr = step_data.stderr
      if stderr.strip():
        errmsg = 'project {} not found'.format(project)
        # Non-empty stderr
        if errmsg not in stderr:
          raise StepFailure('unexpected error: {}'.format(stderr))
        return False
      return True

  def report_manifest_branch_state(self, projects=None, test_data='Repo: info',
                                   test_failure=False):
    """Use 'repo info' to output manifest state to stdout.
    Args:
      projects (list[str]): Projects to limit the info call to, or None to get
        info for all projects.
      test_data (str): Optional data for testing stdout.
      test_failure (bool): Raise StepFailure or not
    Returns:
      (str): Full info on the manifest branch, current branch or
      unmerged branches.
    """
    if test_failure:
      raise StepFailure('tested failure in repo-info step')
    cmd = [self.repo_path, 'info']
    if projects:
      cmd += projects
    stdout = self.m.easy.stdout_step('repo info', cmd,
                                     test_stdout=lambda: test_data)
    return stdout.decode().strip()

  def ensure_pinned_manifest(self, projects=None, regexes=None, test_data=None,
                             step_name=None):
    """Ensure that we know the revision info for all projects.

    If the manifest is not pinned, a pinned manifest is created and logged.

    Args:
      projects (list[str]): Project names or paths to return info for. Defaults
        to all projects.
      regexes (list[str]): list of regexes for matching projects. The matching
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
        pres.logs['pinned-manifest.xml'] = manifest
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
    step_test_data = lambda: self.m.raw_io.test_api.stream_output_text(
        test_data or '<manifest></manifest>')

    cmd = ['manifest']
    if pinned:
      cmd += ['-r']
    if manifest_file:
      cmd += ['-m', manifest_file]

    step_data = self._step(
        cmd, stdout=self.m.raw_io.output_text(add_output_log=True),
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
      list[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
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
      list[ManifestDiff]: An array of `ManifestDiff` namedtuple for any existing
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
              from_revision if from_revision == base else '{} => {}'.format(
                  from_revision, base))
          from_revision = base
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

  def _git_sanitize_checkout(self, root_path, projects=None):
    """Execute cleaning operations to minimize git tree size & check integrity.

    Args:
      root_path (Path): Path to the repo root.
      projects (list[str]): Projects to clean or None to clean all projects.
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

  def _git_clean_checkout(self, root_path, projects=None):
    """Ensure the given repo does not contain untracked files or directories.

    We're assuming that the root path provided has already been validated.

    Args:
      root_path (Path): Path to the repo root.
      projects (list[str]): Projects to clean or None to clean all projects.
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
  def manifest_gitiles_commit(self):
    """Return a Gitiles commit for the repo manifest."""
    with self.m.context(cwd=self._find_root().join('.repo', 'manifests')):
      return self.m.git.gitiles_commit()

  def ensure_synced_checkout(self, root_path, manifest_url, init_opts=None,
                             sync_opts=None, projects=None, final_cleanup=False,
                             sanitize=False):
    """Ensure the given repo checkout exists and is synced.

    Args:
      root_path (Path): Path to the repo root.
      manifest_url (str): Manifest URL for 'repo.init`.
      init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      projects (list[str]): Projects of concern or None if all projects
        are of concern. Used to perform optimizations where possible to only
        operate on the given projects.
      final_cleanup (bool): Used by cache builder to ensure that all locks
        and uncommitted files are cleaned up after the sync.
      sanitize (bool): Should we run `git gc` on all repos.
    """
    repo_state_path = root_path.join('.recipes_state.json')
    manifest_branch = (init_opts.get('manifest_branch') or
                       '') if init_opts else ''
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
    self.m.file.write_proto('Write proto to {}'.format(repo_state_path),
                            repo_state_path, repo_state, 'JSONPB')

    # If we're sanitizing the repo do this before the sync.
    if sanitize:
      self._git_sanitize_checkout(root_path, projects=projects)

    # Clean cache if needed
    self._sync_checkout(root_path, manifest_url, init_opts=init_opts,
                        sync_opts=sync_opts, projects=projects, clean=clean,
                        final_cleanup=final_cleanup)
    repo_state.state = RepoState.STATE_CLEAN

    self.m.file.write_proto('Write proto to {}'.format(repo_state_path),
                            repo_state_path, repo_state, 'JSONPB')
    return True

  def _sync_checkout(self, root_path, manifest_url, init_opts=None,
                     sync_opts=None, projects=None, clean=False,
                     final_cleanup=False):
    """Ensure the given repo checkout exists and is synced.

    Args:
      root_path (Path): Path to the repo root.
      manifest_url (str): Manifest URL for 'repo.init`.
      init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      projects (list[str]): Projects of concern or None if all projects
        are of concern. Used to perform optimizations where possible to only
        operate on the given projects.
      clean (bool): Boolean stating whether the cache is clean.
      final_cleanup (bool): Boolean stating whether to perform a final
        cleanup after the sync.
    """
    with self.m.step.nest('ensure synced checkout') as presentation:
      self.m.file.ensure_directory('ensure root path', root_path)
      with self.m.context(cwd=root_path, infra_steps=True):
        init_opts = dict(init_opts or {}, projects=projects)
        sync_opts = dict(sync_opts or {}, projects=projects)
        manifest_name = init_opts.get('manifest_name')
        # The same value must be passed in both sets of options.
        assert manifest_name == sync_opts.get('manifest_name')
        # Manifest branch must be passed with init_opts
        assert 'manifest_branch' in init_opts, (
            'manifest tracking branch not specified.')
        presentation.step_text = 'cache tracking {} branch'.format(
            json.dumps(init_opts['manifest_branch'], sort_keys=True))
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
            # Remove .repo/manifests and .repo/manifests.git to avoid
            # potential problems when switching to a different manifest
            # repo or branch.
            if self._remove_manifests_git:
              for manifest_dir in ('manifests', 'manifests.git'):
                self.m.file.rmtree('remove .repo/%s' % manifest_dir,
                                   root_path.join('.repo', manifest_dir))

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

  def _binary_selfupdate(self, root_path, verify_repo):
    """Issues a repo selfupdate to update the binary.

    Args"
      root_path (Path): Path to the repo root.
      verify_repo (bool): Whether to verify the signature on repo.
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
