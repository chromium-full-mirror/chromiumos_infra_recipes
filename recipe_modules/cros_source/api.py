# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""

import contextlib
import json

from collections import namedtuple

from recipe_engine import recipe_api

ProjectCommit = namedtuple('ProjectCommit', ['path', 'commit_id'])


class CrosSourceApi(recipe_api.RecipeApi):
  """A module for CrOS-specific source steps."""

  EXTERNAL_MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'
  INTERNAL_MANIFEST_URL = 'https://chrome-internal.googlesource.com/chromeos/manifest-internal'

  def initialize(self):
    """Initialize CrosSourceApi."""
    self._master_path = self.m.path['start_dir'].join('chromiumos_master')
    self._workspace_path = self.m.path['start_dir'].join('chromiumos_workspace')

  @property
  def master_path(self):
    """The "master" checkout path.

    This is a recent version of the source which should not be modified (apart
    from incidental changes like caching) during a build. "Top of tree" logic
    will run from this checkout.
    """
    return self._master_path

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    This is where the build is processed. It will contain the target base
    checkout and any modifications made by the build.
    """
    return self._workspace_path

  @contextlib.contextmanager
  def checkout_overlays_context(self, checkout_path):
    """Returns a context where master and workspace overlays are mounted.

    Args:
      checkout_path (Path): Path to CrOS source checkout.
    """
    with self.m.overlayfs.cleanup_context():
      self.m.overlayfs.mount('master', checkout_path, self.master_path)
      self.m.overlayfs.mount('workspace', checkout_path, self.workspace_path)
      self.m.path.mock_add_paths(self.master_path.join('.repo'))
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
      new_commits = []
      for patch_set in patch_sets:
        project_path = self.find_project_path(patch_set.project,
                                              patch_set.branch)
        with self.m.context(cwd=self.workspace_path.join(project_path)):
          commit_id = self.m.git.fetch_ref(patch_set.git_fetch_url,
                                           patch_set.git_fetch_ref)
          self.m.git.cherry_pick(commit_id)
          new_commit_id = self.m.git.head_commit()
          new_commits.append(ProjectCommit(project_path, new_commit_id))

      return new_commits

  def sync_gitiles_snapshot(self, gitiles_commit):
    """Sync a checkout to the snapshot in |gitiles_commit|."""
    gitiles_url = 'https://%s/%s' % (gitiles_commit.host,
                                     gitiles_commit.project)

    step_test_data = lambda: self.m.gitiles.test_api.make_encoded_file('<manifest></manifest>')
    snapshot_xml = self.m.gitiles.download_file(gitiles_url, 'snapshot.xml',
                                                branch=gitiles_commit.id,
                                                step_test_data=step_test_data)

    self.m.repo.sync_manifest(manifest_data=snapshot_xml, detach=True,
                              optimized_fetch=True)

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
