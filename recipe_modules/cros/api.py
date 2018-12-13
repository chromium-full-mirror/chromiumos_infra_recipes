# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for running CrOS infra scripts."""

from recipe_engine import recipe_api


class CrosApi(recipe_api.RecipeApi):
  """A module forCrOS infra script steps."""

  def initialize(self):
    self._master_path = self.m.path['start_dir'].join('chromiumos_master')
    self._workspace_path = self.m.path['start_dir'].join('chromiumos_workspace')

  @property
  def master_path(self):
    return self._master_path

  @property
  def workspace_path(self):
    return self._workspace_path

  def _chroot_step(self, name, cmd, **kwargs):
    """Runs a step within the configured workspace and cros_sdk chroot.

    Args:
      * name (str): The name of the step.
      * cmd (list[str]): A command and arguments to run.
      * kwargs: Keyword arguments to pass to cros_sdk.run.

    Returns:
      See 'step.__call__'.
    """
    with self.m.context(cwd=self.workspace_path):
      return self.m.cros_sdk.run(name, cmd, **kwargs)

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
      step_data = self.m.step(
          'find %s [%s]' % (project, branch), cmd,
          stdout=self.m.raw_io.output(), step_test_data=
          lambda: self.m.raw_io.test_api.stream_output('src/project'))
      return step_data.stdout.strip()

  def regen_portage_cache(self, repo_name, jobs=32):
    """Regenerate the portage cache with 'egencache' in the chroot.

    Args:
      repo_name (str): Portage repo name, passed to 'egencache --repo'.
      jobs (int): Parallel processes to run, passed to 'egencache --jobs'.
    """
    cmd = ['egencache', '--update', '--repo', repo_name, '--jobs', '%d' % jobs]
    self._chroot_step('regen_portage_cache %s' % repo_name, cmd)

  def uprev_portage_packages(self):
    """Uprevs portage packages for all boards."""
    cmd = [
      'chromite/bin/cros_mark_as_stable', 'commit',
      '--buildroot', self.workspace_path,
      '--overlay-type', 'both'
    ]
    if self.m.dev.dryrun:
      cmd += ['--dryrun']
    with self.m.context(cwd=self.workspace_path):
      return self.m.step('uprev portage packages', cmd)
