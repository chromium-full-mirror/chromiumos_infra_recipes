# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the cros branch tool."""

from recipe_engine import recipe_api
from PB.chromiumos.branch import Branch


class CrosBranchApi(recipe_api.RecipeApi):
  """A module for calling cros branch."""

  def initialize(self):
    self._branch_util_path = None

  def __call__(self,
               cmd,
               step_name=None,
               force=False,
               push=False,
               **kwargs):
    """Call cros branch with the given args.

    Args:
      cmd: Command to be run with cros branch
      step_name (str): Message to use for step. Optional.
      force (bool): If True, cros branch will be run with --force.
      push (bool): If True, cros branch will be run with --push.
      kwargs: Keyword arguments for recipe_engine/step.
    """
    branch_args = []
    if force:
      branch_args.append('--force')
    if push:
      branch_args.append('--push')

    self._ensure_branch_util()
    self.m.step(step_name or '%s branch' % cmd[0],
                [self._branch_util_path] + cmd + branch_args,
                **kwargs)

  def create_from_file(self, manifest_file, branch, manifest_src=None,
                       **kwargs):
    """Call `cros branch create`, branching from the file specified in
      manifest_file.

    Args:
      manifest_file (recipe_engine.config_types.Path): Path to manifest file.
          This recipe assumes that it is at the top level of a ChromeOS
          checkout.
      branch (chromiumos.Branch): Branch to be created.
      kwargs: Keyword arguments for recipe_engine/step.
        Accepts the same keyword arguments as __call__.

    Returns:
      TODO(jackneus): return branch name?
    """
    cmd = ['create', '--file', manifest_file]

    # Branch unspecified.
    if not branch or branch.type == Branch.UNSPECIFIED:
      raise ValueError('Branch type is required.')
    # Custom branch. Check for name.
    elif branch.type == Branch.CUSTOM:
      if branch.name:
        cmd.extend(['--custom', branch.name])
      else:
        raise ValueError('Branch name required for custom branch.')
    # Standard branch type.
    else:
      cmd.append('--' + Branch.BranchType.Name(branch.type).lower())

    if branch.descriptor:
      cmd.extend(['--descriptor', branch.descriptor])

    kwargs.setdefault('step_name',
      'create branch from manifest %s' % manifest_file)
    self(cmd, **kwargs)

  def rename(self, branch, new_branch_name, **kwargs):
    """Call `cros branch rename` with the appropriate arguments.

    Args:
      branch (chromiumos.Branch): Branch to be renamed.
      new_branch_name (str): New branch name.
      kwargs: Keyword arguments for cros branch/recipe_engine/step.
        Accepts the same keyword arguments as __call__.
    """
    cmd = ['rename']

    if branch and branch.name:
      cmd.append(branch.name)
    else:
      raise ValueError('Branch name is required.')

    if new_branch_name:
      cmd.append(new_branch_name)
    else:
      raise ValueError('New branch name is required.')

    kwargs.setdefault('step_name',
      'rename branch %s to %s' % (branch.name, new_branch_name))
    self(cmd, **kwargs)

  def delete(self, branch, **kwargs):
    """Call `cros branch delete` with the appropriate arguments.

    Args:
      branch (chromiumos.Branch): Branch to be deleted.
      kwargs: Keyword arguments for cros branch/recipe_engine/step.
        Accepts the same keyword arguments as __call__.
    """
    cmd = ['delete']

    if branch and branch.name:
      cmd.append(branch.name)
    else:
      raise ValueError('Branch name is required.')

    kwargs.setdefault('step_name', 'delete branch %s' % branch.name)
    self(cmd, **kwargs)

  def _ensure_branch_util(self):
    """Ensure the branch_util cli is installed."""
    if self._branch_util_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure branch_util'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._branch_util_path = cipd_dir.join('branch_util')
