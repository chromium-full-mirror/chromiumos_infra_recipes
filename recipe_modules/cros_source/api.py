# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""

import contextlib
import json

from collections import namedtuple

from recipe_engine import recipe_api
from util import exponential_retry

ProjectCommit = namedtuple('ProjectCommit', ['path', 'commit_id'])

DEFAULT_CACHE_SYNC_OPTS = dict(
    current_branch=True,
    detach=True,
    force_sync=True,
    no_tags=True,
    jobs=32,
    optimized_fetch=True,
    timeout=3600,
)

STAGING_INIT_OPTS = dict(repo_branch='next')


class CrosSourceApi(recipe_api.RecipeApi):
  """A module for CrOS-specific source steps."""

  EXTERNAL_HOST = 'chromium.googlesource.com'
  EXTERNAL_PROJECT = 'chromiumos/manifest'
  INTERNAL_HOST = 'chrome-internal.googlesource.com'
  INTERNAL_PROJECT = 'chromeos/manifest-internal'

  EXTERNAL_MANIFEST_URL = 'https://{}/{}'.format(EXTERNAL_HOST,
                                                 EXTERNAL_PROJECT)
  INTERNAL_MANIFEST_URL = 'https://{}/{}'.format(INTERNAL_HOST,
                                                 INTERNAL_PROJECT)

  def __init__(self, properties, *args, **kwargs):
    super(CrosSourceApi, self).__init__(*args, **kwargs)
    self._snapshot_isolate = (properties.snapshot_isolate
                              if properties.HasField('snapshot_isolate')
                              else None)

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

    This is the cached version of source, usually updated once at the beginning
    of a build and then mounted into the master and/or workspace paths.
    """
    return self.m.path['cache'].join('chromiumos')

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    This is where the build is processed. It will contain the target base
    checkout and any modifications made by the build.
    """
    return self.m.path['start_dir'].join('chromiumos_workspace')

  @property
  def snapshot_isolated_hash(self):
    """Returns the snapshot isolate hash in use or None."""
    return (self._snapshot_isolate.isolated_hash if self._snapshot_isolate
            else None)

  def ensure_synced_cache(self, manifest_url=INTERNAL_MANIFEST_URL,
                          init_opts=None, sync_opts=None,
                          cache_path_override=None, is_staging=False):
    """Ensure the configured repo cache exists and is synced.

    Args:
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
      * cache_path_override (Path): Path to sync into. If None, the cache_path
      property is used.
      * is_staging (bool): Flag to indicate canary staging environment
    """
    init_opts = init_opts or {}
    if is_staging:
      init_opts.update(STAGING_INIT_OPTS)
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, **(sync_opts or {}))
    cache_path = cache_path_override or self.cache_path
    self.m.repo.ensure_synced_checkout(cache_path, manifest_url,
                                       init_opts=init_opts, sync_opts=sync_opts)

  @contextlib.contextmanager
  def checkout_overlays_context(self):
    """Returns a context where chromiumos and workspace overlays are mounted."""
    with self.m.overlayfs.cleanup_context():
      self.m.overlayfs.mount('chromiumos', self.preload_path, self.cache_path,
                             persist=True)
      self.m.overlayfs.mount('workspace', self.cache_path, self.workspace_path)
      self.m.path.mock_add_paths(self.cache_path.join('.repo'))
      self.m.path.mock_add_paths(self.workspace_path.join('.repo'))
      yield

  def find_project_path(self, project, branch):
    """Find the source path for a given project in the workspace.

    Args:
      project (str): The project name to find a source path for.
      branch (str): The branch name to find a source path for.

    Returns:
      The path value for the found project.
    """
    if not branch.startswith('refs/'):
      branch = 'refs/heads/%s' % branch
    with self.m.context(cwd=self.workspace_path):
      for project_info in self.m.repo.project_infos([project]):
        if project_info.branch == branch:
          return project_info.path

      raise self.m.step.StepFailure(
          'No path found for project %r branch %r' % (project, branch))

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
        project_path = self.find_project_path(patch_set.project,
                                              patch_set.branch)
        with self.m.context(cwd=self.workspace_path.join(project_path)):
          commit_id = self.m.git.fetch_ref(patch_set.git_fetch_url,
                                           patch_set.git_fetch_ref)
          merged = self.m.git.merge_silent_fail(
              commit_id, 'merge gerrit changes', infra_step=False)
          if not merged:
            self.m.git.merge_abort()
            presentation = self.m.step.active_result.presentation
            presentation.status = self.m.step.SUCCESS
            presentation.step_text = (
                'merge failed. will try cherry-pick instead')
            self.m.git.cherry_pick(commit_id, infra_step=False)

          new_commit_id = self.m.git.head_commit()
          new_commits.append(ProjectCommit(project_path, new_commit_id))

      return new_commits

  @exponential_retry(retries=3, condition=lambda e: e.had_timeout)
  def sync_snapshot(self, gitiles_commit):
    """Sync a checkout to the snapshot."""
    with self.m.step.nest('sync to snapshot'):
      snapshot_xml = self._get_snapshot(gitiles_commit)
      self.m.repo.sync_manifest(manifest_data=snapshot_xml, detach=True,
                                optimized_fetch=True)

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
