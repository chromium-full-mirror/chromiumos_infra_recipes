# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the cros branch tool."""

from recipe_engine import recipe_api
from PB.chromiumos.branch import Branch


class CrosBranchApi(recipe_api.RecipeApi):
  """A module for calling cros branch."""

  def __call__(self,
               cmd,
               step_name=None,
               root=None,
               force=False,
               push=False,
               **kwargs):
    """Call cros branch with the given args.

    Args:
      cmd: Command to be run with cros branch
      step_name (str): Message to use for step. Optional.
      root (str): Root of checkout to be used with cros branch tool (with
        --root). If not set, no root will be used.
      force (bool): If True, cros branch will be run with --force.
      push (bool): If True, cros branch will be run with --push.
      kwargs: Keyword arguments for recipe_engine/step.
    """
    branch_args = []
    if root:
      branch_args.extend(['--root', root])
    if force:
      branch_args.append('--force')
    if push:
      branch_args.append('--push')

    with self.m.depot_tools.on_path():
      self.m.step(step_name or '%s branch' % cmd[0],
                  ['chromite/bin/cros', 'branch'] + branch_args + cmd,
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
    cmd = ['create', '--yes', '--file', manifest_file]

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
