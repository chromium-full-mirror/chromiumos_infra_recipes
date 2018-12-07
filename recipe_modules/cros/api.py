# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for running CrOS infra scripts."""

from recipe_engine import recipe_api


class CrosApi(recipe_api.RecipeApi):
  """A module forCrOS infra script steps."""

  def get_config_defaults(self):
    return {
        'MASTER_SRC_PATH': self.m.path['start_dir'].join('chromiumos_master'),
        'WORKSPACE_SRC_PATH': self.m.path['start_dir'].join('chromiumos'),
        'CHROOT_PATH': self.m.path['start_dir'].join('chroot'),
    }

  @property
  def master_src_path(self):
    """Returns the Path where the master branch repo should be checked out.

    'Unbranched' infra scripts will be executed from here.
    """
    return self.c.MASTER_SRC_PATH

  @property
  def workspace_src_path(self):
    """Returns the Path where the repo branch under test should be checked out.

    The CrOS SDK will be executed from here, along with any other 'branched'
    infra scripts.
    """
    return self.c.WORKSPACE_SRC_PATH

  @property
  def chroot_path(self):
    """Returns the Path where the CrOS SDK chroot should be."""
    return self.c.CHROOT_PATH

  def _cros_sdk_step(self, name, cmd, **kwargs):
    """Runs a step within the configured workspace and cros_sdk chroot.

    Args:
      * name (str): The name of the step.
      * chroot_path (str|Path): Path to the chroot.
      * cmd (list[str]): A command and arguments to run.
      * kwargs: Keyword arguments to pass to cros_sdk.run.

    Returns:
      See 'step.__call__'.
    """
    with self.m.context(cwd=self.workspace_src_path):
      return self.m.cros_sdk.run(name, self.chroot_path, cmd, **kwargs)

  def find_project_path(self, project, branch):
    """Find the source path for a given project.

    Args:
      project (str): The project name to find a source path for.
      branch (str): The branch name to find a source path for.

    Returns:
      The path value for the found project.
    """
    with self.m.context(cwd=self.master_src_path):
      cmd = [
          'chromite/scripts/find_project_path', '--project', project,
          '--branch', branch
      ]
      return self.m.step(
          'find %s [%s]' % (project, branch), cmd,
          stdout=self.m.raw_io.output(), step_test_data=
          lambda: self.m.raw_io.test_api.stream_output('src/project')
      ).stdout.strip()

  def regen_portage_cache(self, repo_name, jobs=32):
    """Regenerate the portage cache with 'egencache' in the chroot.

    Args:
      repo_name (str): Portage repo name, passed to 'egencache --repo'.
      jobs (int): Parallel processes to run, passed to 'egencache --jobs'.
    """
    cmd = ['egencache', '--update', '--repo', repo_name, '--jobs', '%d' % jobs]
    self._cros_sdk_step('regen_portage_cache %s' % repo_name, cmd)
