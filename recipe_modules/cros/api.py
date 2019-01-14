# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for CrOS CI."""

from recipe_engine import recipe_api


class CrosApi(recipe_api.RecipeApi):
  """A module for CrOS CI steps."""

  def initialize(self):
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

  def cherry_pick_changes(self, changes):
    """Apply changes to the workspace.

    Args:
      changes (list[change.Change]): A list of Changes to cherry-pick.
    """
    with self.m.step.nest('cherry-pick changes'):
      for change in changes:
        project_path = self.find_project_path(change.project, change.branch)
        with self.m.context(self.workspace_path.join(project_path)):
          commit_id = self.m.git.fetch_ref(change.git_fetch_url,
                                           change.git_fetch_ref)
          self.m.git.cherry_pick(commit_id)
