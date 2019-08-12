# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with git cl."""

import re

from recipe_engine import recipe_api


class GitClApi(recipe_api.RecipeApi):
  """A module for interacting with git cl."""

  def __call__(self, *args, **kwargs):
    with self.m.depot_tools.on_path():
      return self.m.depot_tools_git_cl(*args, **kwargs)

  def __getattr__(self, name):
    attr = getattr(self.m.depot_tools_git_cl, name)

    assert callable(attr), 'unexpected uncallable attr'

    # Ensure depot_tools is on path.
    def wrapper(*args, **kwargs):
      with self.m.depot_tools.on_path():
        return attr(*args, **kwargs)

    return wrapper

  def status(self, field=None, fast=False, **kwargs):
    """Run `git cl status` with given arguments.

    Args:
      field: Set --field to this value.
      fast: Set --fast.
      kwargs: Passed to recipe_engine/step.

    Returns:
      str: The command output.
    """
    assert 'stdout' not in kwargs, 'cannot set stdout'

    step_name = kwargs.pop('step_name', None)
    if step_name is not None:
      kwargs['name'] = step_name

    args = []
    if field is not None:
      args.append('--field')
      args.append(field)
    if fast:
      args.append('--fast')
    return self(
        'status', args, stdout=self.m.raw_io.output(), **kwargs
    ).stdout.strip()
