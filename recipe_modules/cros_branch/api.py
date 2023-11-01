# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the cros branch tool."""

import re

from PB.chromiumos.branch import Branch

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

BRANCH_UTIL_REGEX = r'Creating branch: (?P<branch>.*)\s*'


class CrosBranchApi(recipe_api.RecipeApi):
  """A module for calling cros branch."""

  def __call__(self, cmd, step_name=None, force=False, push=False, **kwargs):
    """Call cros branch with the given args.

    Args:
      cmd: Command to be run with cros branch
      step_name (str): Message to use for step. Optional.
      force (bool): If True, cros branch will be run with --force.
      push (bool): If True, cros branch will be run with --push.
      kwargs: Keyword arguments for recipe_engine/step.

    Returns:
      branch_name (string): The name of the created branch, or None.
    """
    branch_args = ['--skip-group-check']
    if force:
      branch_args.append('--force')
    if push:
      branch_args.append('--push')

    step_data = self.m.gobin.call(
        'branch_util', cmd + branch_args, step_name=step_name or
        f'{cmd[0]} branch',
        stdout=self.m.raw_io.output_text(name='branch_util stdout',
                                         add_output_log=True), **kwargs)

    res = re.search(BRANCH_UTIL_REGEX, step_data.stdout)
    if not res:
      return None
    return res.group('branch')

  def _create(self, branch, branch_util_args, **kwargs):
    cmd = ['create'] + branch_util_args

    # Branch unspecified.
    if not branch or branch.type == Branch.UNSPECIFIED:
      raise StepFailure('Branch type is required.')
    # Custom branch. Check for name.
    if branch.type == Branch.CUSTOM:
      if branch.name:
        cmd.extend(['--custom', branch.name])
      else:
        raise StepFailure('Branch name required for custom branch.')
    # Standard branch type.
    else:
      cmd.append('--' + Branch.BranchType.Name(branch.type).lower())

    if branch.descriptor:
      cmd.extend(['--descriptor', branch.descriptor])

    return self(cmd, **kwargs)

  def create_from_buildspec(self, source_version, branch, **kwargs):
    """Call `cros branch create`, branching from the appropriate buildspec
      manifest.

    Args:
      source_version (str): Version to branch from.
        Must have a valid manifest in manifest-versions/buildspecs or branch_util
        will fail.
      branch (chromiumos.Branch): Branch to be created.
      kwargs: Keyword arguments for recipe_engine/step.
        Accepts the same keyword arguments as __call__.

    Returns:
      branch_name (string): The name of the created branch, or None.
    """
    with self.m.step.nest('parse source_version'):
      version = self.m.cros_version.Version.from_string(source_version)
      if not version:
        raise StepFailure('invalid version: {}'.format(source_version))

    kwargs.setdefault(
        'step_name',
        'create branch from buildspec manifest %s' % version.buildspec_filename)
    manifest_args = ['--buildspec-manifest', version.buildspec_filename]

    return self._create(branch, manifest_args, **kwargs)

  def create_from_file(self, manifest_file, branch, **kwargs):
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
      branch_name (string): The name of the created branch, or None.
    """
    manifest_args = ['--file', manifest_file]

    kwargs.setdefault('step_name',
                      'create branch from manifest %s' % manifest_file)
    return self._create(branch, manifest_args, **kwargs)

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
      raise StepFailure('Branch name is required.')

    if new_branch_name:
      cmd.append(new_branch_name)
    else:
      raise StepFailure('New branch name is required.')

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
      raise StepFailure('Branch name is required.')

    kwargs.setdefault('step_name', 'delete branch %s' % branch.name)
    self(cmd, **kwargs)
