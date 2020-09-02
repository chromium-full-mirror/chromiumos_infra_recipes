# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""

import contextlib
import json

from collections import namedtuple

from recipe_engine import recipe_api
from recipe_engine.util import exponential_retry

ProjectCommit = namedtuple('ProjectCommit', ['path', 'commit_id'])

# Default sync options for syncing the named cache.
DEFAULT_CACHE_SYNC_OPTS = dict(current_branch=True, detach=True,
                               force_sync=True, jobs=8, no_tags=True,
                               optimized_fetch=True, retry_fetches=8,
                               timeout=3600)

STAGING_INIT_OPTS = dict(repo_branch='master')

# Default options for checking out a branch.
DEFAULT_CHECKOUT_SYNC_OPTS = dict(jobs=8, optimized_fetch=True, timeout=3600,
                                  retry_fetches=8)


class CrosSourceApi(recipe_api.RecipeApi):
  """A module for CrOS-specific source steps."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosSourceApi, self).__init__(*args, **kwargs)
    self._snapshot_isolate = (
        properties.snapshot_isolate
        if properties.HasField('snapshot_isolate') else None)
    self._enable_custom_overlays = properties.enable_custom_overlays

  @property
  def preload_path(self):
    """The cached image checkout path.

    This is the cached version of source that is included in the base image of
    the bot, used as an initial reference path.
    """
    return '/preload/chromeos'

  @property
  def cache_path(self):
    """The cached checkout path.

    This is the cached version of source (the internal manifest checkout),
    usually updated once at the beginning of a build and then mounted into the
    master and/or workspace paths.
    """
    return self.m.path['cache'].join('chromiumos')

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    This is where the build is processed. It will contain the target base
    checkout and any modifications made by the build.
    """
    return self.m.src_state.workspace_path

  @property
  def snapshot_isolated_hash(self):
    """Returns the snapshot isolate hash in use or None."""
    return (self._snapshot_isolate.isolated_hash
            if self._snapshot_isolate else None)

  def _validate_args(self, manifest_url, local_manifest, groups, cache_path):
    """Ensure the args to ensure_synced_cache are to a supported configuration.

    Supported configurations include:
      - INTERNAL: Sync the internal manifest to self.cache_path.
      - CUSTOM: Sync any manifest to any path other than
        self.cache_path.

    Args:
      manifest_url (str): Manifest URL for 'repo.init`.
      local_manifest (repo.LocalManifest): Local manifest to add or None if not
        syncing a local manifest.
      groups (list[str]): List of manifest groups to checkout.
      cache_path (Path): Path to sync into. If None, the cache_path
        property is used.

    Returns:
      If the configuration is supported, the type of configuration.
    """
    if cache_path == self.cache_path:
      if (manifest_url != self.m.src_state.internal_manifest.url or
          local_manifest or groups):
        raise ValueError(
            "Only the internal manifest can be synced to the chromiumos cache path."
        )
      return "INTERNAL"
    return "CUSTOM"

  def ensure_synced_cache(self, manifest_url=None, init_opts=None,
                          sync_opts=None, cache_path_override=None,
                          is_staging=False, projects=None, gitiles_commit=None):
    """Ensure the configured repo cache exists and is synced.

    Args:
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * cache_path_override (Path): Path to sync into. If None, the cache_path
      property is used.
      * is_staging (bool): Flag to indicate canary staging environment
      * projects (List[str]): Projects to limit the sync to, or None to sync
      all projects.
      * gitiles_commit (GitilesCommit): The gitiles_commit, or None to use the
      current value.
    """
    if self._enable_custom_overlays:
      self.m.overlayfs.mount('chromiumos', self.preload_path, self.cache_path,
                             persist=True)
      self.m.path.mock_add_paths(self.cache_path.join('.repo'))
      self.m.overlayfs.mount('workspace', self.cache_path, self.workspace_path)
      self.m.path.mock_add_paths(self.workspace_path.join('.repo'))

    cache_path = cache_path_override or self.cache_path
    manifest_url = manifest_url or self.m.src_state.internal_manifest.url

    gitiles_commit = gitiles_commit or self.m.src_state.gitiles_commit
    gitiles_commit = (
        gitiles_commit if gitiles_commit.host else
        self.m.src_state.internal_manifest.as_gitiles_commit_proto)
    init_opts = init_opts or {}
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, **(sync_opts or {}))
    local_manifest = init_opts.get('local_manifest')
    groups = init_opts.get('groups')
    verbose = init_opts.get('verbose')
    retry_fetches = sync_opts.get('retry_fetches')

    configuration = self._validate_args(manifest_url, local_manifest, groups,
                                        cache_path)
    if configuration == 'INTERNAL':
      self._sync_cached_dir(retry_fetches, projects, verbose, external=False,
                            is_staging=is_staging)
    else:
      self.m.repo.ensure_synced_checkout(cache_path, manifest_url,
                                         init_opts=init_opts,
                                         sync_opts=sync_opts, projects=projects)

  def checkout_branch(self, manifest_url, manifest_branch, init_opts=None,
                      sync_opts=None, step_name=None):
    """Check out a branch of the current manifest.

    Note: If there are changes applied when this is called, repo will try to
    rebase them to the new branch.

    Args:
      * manifest_branch (str): The branch to check out, such as
          'release-R86-13421.B'
      * manifest_url (str): The manifest url.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * step_name (str): Name for the step, or None for default.
    """
    with self.m.context(cwd=self.workspace_path), \
        self.m.step.nest(step_name or 'checkout branch %s' % manifest_branch):
      my_init_opts = {}
      my_init_opts.update(init_opts or {})
      my_init_opts['manifest_branch'] = manifest_branch
      self.m.repo.init(manifest_url, **my_init_opts)

      my_sync_opts = dict(**DEFAULT_CHECKOUT_SYNC_OPTS)
      my_sync_opts.update(sync_opts or {})
      self.m.repo.sync(**my_sync_opts)

  def fetch_snapshot_shas(self, count=7 * 24 * 2):
    """Return snapshot SHAs for the manifest.

    Return SHAs for the most recent |count| commits in the manifest.  The
    default is to fetch 7 days worth of snapshots, based on (an assumed) 2
    snapshots per hour.

    Args:
      * count (int): How many SHAs to return.

    Returns:
      (list[str]) The list of snapshot SHAs.
    """
    snapshot = self.m.src_state.gitiles_commit
    manifest_dir = self.m.path.basename(snapshot.project)

    with self.m.context(cwd=self.workspace_path.join(manifest_dir)):
      return self.m.git.fetch_refs(
          'https://{}/{}'.format(snapshot.host, snapshot.project), snapshot.id,
          count=count)

  def _sync_cached_dir(self, retry_fetches=None, projects=None, verbose=False,
                       external=False, is_staging=False):
    """Sync to the chromiumos overlay.

    Args:
      retry_fetches (int): The number of times to retry retriable fetches.
      projects (List[str]): Projects to limit the sync to, or None to sync
        all projects.
      verbose (bool): Whether to produce verbose output.
      external (bool): Flag to indiciate syncing to the external manifest.
      is_staging (bool): Flag to indicate staging environment
    """
    sync_path = self.cache_path
    manifest_url = self.m.src_state.internal_manifest.url

    init_opts = dict(verbose=verbose)
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, verbose=verbose,
                     retry_fetches=retry_fetches)

    self.m.repo.ensure_synced_checkout(sync_path, manifest_url,
                                       init_opts=init_opts, sync_opts=sync_opts,
                                       projects=projects)

  @contextlib.contextmanager
  def checkout_overlays_context(self):
    """Returns a context where overlays can be mounted."""
    with self.m.overlayfs.cleanup_context():
      if not self._enable_custom_overlays:
        self.m.overlayfs.mount('chromiumos', self.preload_path, self.cache_path,
                               persist=True)
        self.m.path.mock_add_paths(self.cache_path.join('.repo'))
        self.m.overlayfs.mount('workspace', self.cache_path,
                               self.workspace_path)
        self.m.path.mock_add_paths(self.workspace_path.join('.repo'))
      yield

  def find_project_paths(self, project, branch):
    """Find the source paths for a given project in the workspace.

    Will only include multiple results if the same project,branch is mapped
    more than once in the manifest.

    Args:
      project (str): The project name to find a source path for.
      branch (str): The branch name to find a source path for.

    Returns:
      list(str), The path values for the found project.
    """
    if not branch.startswith('refs/'):
      branch = 'refs/heads/%s' % branch
    paths = []
    with self.m.context(cwd=self.workspace_path):
      for project_info in self.m.repo.project_infos([project]):
        if project_info.branch == branch:
          paths.append(project_info.path)

      if not paths:
        raise self.m.step.StepFailure('No path found for project %r branch %r' %
                                      (project, branch))
      return paths

  def apply_gerrit_patch_sets(self, patch_sets):
    """Apply Gerrit patch sets to the workspace.

    Args:
      patch_sets (List[gerrit.PatchSet]): A list of patch sets to cherry-pick.

    Returns:
      List[ProjectCommit]: A list of commits from cherry-picked patch sets.
    """
    with self.m.step.nest('apply gerrit patch sets'):
      # Disable packRefs before doing merges. See https://crbug.com/1057878.
      self.m.git.set_global_config(['gc.packRefs', 'false'])
      new_commits = []
      for patch_set in patch_sets:
        project_paths = self.find_project_paths(patch_set.project,
                                                patch_set.branch)
        for project_path in project_paths:
          with self.m.context(cwd=self.workspace_path.join(project_path)):
            commit_id = self.m.git.fetch_ref(patch_set.git_fetch_url,
                                             patch_set.git_fetch_ref)
            merged = self.m.git.merge_silent_fail(commit_id,
                                                  'merge gerrit changes',
                                                  infra_step=False)
            if not merged:
              self.m.git.merge_abort()
              if self.m.git.is_merge_commit(commit_id):
                raise self.m.step.StepFailure('%s failed, aborting, this '
                                              'commit is a merge so we can '
                                              'not cherry-pick' % commit_id)
              presentation = self.m.step.active_result.presentation
              presentation.status = self.m.step.SUCCESS
              presentation.step_text = (
                  'merge failed. will try cherry-pick instead')
              self.m.git.cherry_pick(commit_id, infra_step=False)

            new_commit_id = self.m.git.head_commit()
            new_commits.append(ProjectCommit(project_path, new_commit_id))

      return new_commits

  retry_timeouts = lambda e: getattr(e, 'had_timeout', False)

  @exponential_retry(retries=3, condition=retry_timeouts)
  def sync_snapshot(self, gitiles_commit, manifest_url=None):
    """Sync a checkout to the snapshot.

    Args:
      gitiles_commit (GitilesCommit): commit to sync to
      manifest_url: URL of manifest repo.  Default: internal manifest
    """
    manifest_url = manifest_url or self.m.src_state.internal_manifest.url
    with self.m.step.nest('sync to snapshot'):
      snapshot_xml = self._get_snapshot(gitiles_commit)
      self.m.repo.sync_manifest(manifest_url, manifest_data=snapshot_xml,
                                detach=True, optimized_fetch=True,
                                retry_fetches=8)

  def _get_snapshot(self, gitiles_commit):
    """Returns the snapshot to use.

    Returns the snapshot to use. If a custom snapshot has been provided
    via an input property, that will be used. Otherwise it will fall back
    to the typical syncing to the gitiles_commit.
    """
    if self._snapshot_isolate:
      return self._get_snapshot_from_isolate()
    return self._get_snapshot_from_gitiles(gitiles_commit)

  def _get_snapshot_from_isolate(self):
    """Returns the snapshot to use from isolate"""
    si = self._snapshot_isolate
    snapshot_dir = self.m.path.mkdtemp('snapshot')
    self.m.isolated.download('download snapshot.xml from isolate',
                             isolated_hash=si.isolated_hash,
                             isolate_server=si.isolate_server,
                             output_dir=snapshot_dir)
    return self.m.file.read_text('read snapshot.xml',
                                 snapshot_dir.join('snapshot.xml'),
                                 test_data='<manifest></manifest>')

  def _get_snapshot_from_gitiles(self, gitiles_commit):
    """Returns the snapshot to use from gitiles."""
    gitiles_url = 'https://%s/%s' % (gitiles_commit.host,
                                     gitiles_commit.project)

    step_test_data = lambda: self.m.gitiles.test_api.make_encoded_file(
        '<manifest></manifest>')

    return self.m.gitiles.download_file(
        gitiles_url, 'snapshot.xml', branch=gitiles_commit.id,
        step_test_data=step_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)

  def create_project_commits_archive(self, archive_path, project_commits):
    """Creates an archive with the given project commits from the workspace.

    This uses `git bundle` to efficiently store diffs. The recipient of this
    archive must have appropriate parent commits locally available to use
    this archive with 'checkout_project_commits_archive'.

    Args:
      archive_path (Path): Path to archive file to create. Uses the 'archive'
        module and inherits its archive type file extension detection.
      project_commits (List[ProjectCommit]): Commits to add to archive. Must be
        in patch application order.
    """
    with self.m.step.nest('create project commits archive'):
      # Find first commit for each project and make a reference to its parent.
      project_base_commits = {}
      for project_commit in project_commits:
        project_base_commits.setdefault(project_commit.path,
                                        '%s^' % project_commit.commit_id)

      # NOTE: The contents of this archive are an implementation detail of
      # this module. For each project with commit(s) in the archive, a `git
      # bundle` file is included in the archive at
      # 'projects/<project path>/bundle'.
      archive_root = self.m.path.mkdtemp('create_project_commits_archive')
      package = self.m.archive.package(archive_root)
      for project_relpath, base_commit_id in project_base_commits.items():
        archive_project_path = archive_root.join('projects', project_relpath)
        self.m.file.ensure_directory('project path', archive_project_path)
        with self.m.context(cwd=self.workspace_path.join(project_relpath)):
          bundle_path = archive_project_path.join('bundle')
          self.m.git.create_bundle(bundle_path, base_commit_id, 'HEAD')
          package.with_file(bundle_path)

      # A metadata.json file includes information about the included bundles.
      metadata_path = archive_root.join('metadata.json')
      metadata = {'project_paths': project_base_commits.keys()}
      self.m.file.write_text('metadata.json', metadata_path,
                             json.dumps(metadata))
      package.with_file(metadata_path)

      package.archive('create archive', archive_path)

  def checkout_project_commits_archive(self, archive_path):
    """Checkout the commits in the given archive file into the workspace.

    See 'create_project_commits_archive'. The local source tree must have all
    appropriate parent commits locally available to apply an archive.

    Args:
      archive_path (Path): Path to the archive.

    Returns:
      List[str]: List of project paths with commits in the archive.
    """
    with self.m.step.nest('checkout project commits archive'):
      # The archive root must not exist prior to 'extract'.
      archive_workdir = self.m.path.mkdtemp('checkout_project_commits_archive')
      archive_root = archive_workdir.join('archive')
      self.m.archive.extract('extract archive', archive_path, archive_root)

      metadata_path = archive_root.join('metadata.json')
      metadata = json.loads(
          self.m.file.read_text(
              'metadata.json', metadata_path,
              test_data='{"project_paths": ["a/b", "a/b/c"]}'))

      # Checkout bundles into their projects.
      for project_relpath in metadata['project_paths']:
        with self.m.context(cwd=self.workspace_path.join(project_relpath)):
          bundle_path = archive_root.join(project_relpath, 'bundle')
          self.m.git.fetch_ref(bundle_path, 'HEAD')
          self.m.git.checkout('FETCH_HEAD')

      return metadata['project_paths']
