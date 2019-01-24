# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS source."""

import os.path

from collections import namedtuple

from recipe_engine import recipe_api

ProjectCommit = namedtuple('ProjectCommit', ['path', 'commit_id'])


class CrosSourceApi(recipe_api.RecipeApi):
  """A module for CrOS-specific source steps."""

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

  def find_project_path(self, project, branch):
    """Find the source path for a given project.

    Args:
      project (str): The project name to find a source path for.
      branch (str): The branch name to find a source path for.

    Returns:
      The path value for the found project.
    """
    cmd = [
        'chromite/scripts/find_project_path', '--project', project, '--branch',
        branch
    ]
    with self.m.context(cwd=self.master_path):
      return self.m.easy.stdout_step('find %s [%s]' % (project, branch), cmd,
                                     test_stdout='src/project').strip()

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

      # Find all project bundle files extracted from archive.
      project_bundles = {}
      with self.m.context(cwd=archive_root.join('projects')):
        find_stdout = self.m.easy.stdout_step(
            'find bundles',
            ['find', '.', '-name', 'bundle', '-type', 'f', '-print0'],
            test_stdout='a/b/bundle\0a/b/c/bundle\0')
        for bundle_relpath in find_stdout.rstrip('\0').split('\0'):
          project_relpath = os.path.dirname(bundle_relpath)
          bundle_path = self.m.context.cwd.join(bundle_relpath)
          project_bundles[project_relpath] = bundle_path

      # Checkout bundles into their projects.
      for project_relpath, bundle_path in project_bundles.items():
        with self.m.context(cwd=self.workspace_path.join(project_relpath)):
          self.m.git.fetch_ref(bundle_path, 'HEAD')
          self.m.git.checkout('FETCH_HEAD')

      return project_bundles.keys()
