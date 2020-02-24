# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the git_footers script.."""

from recipe_engine import recipe_api


class GitFootersApi(recipe_api.RecipeApi):
  """A module for calling git_footers."""

  def __call__(self, *args, **kwargs):
    """Call git_footers.py with the given args.

    Args:
      args: Arguments for git_footers.py
      kwargs: Keyword arguments for recipe_engine/python.

    Returns:
      list[str]: All matching footer values, or None
    """
    kwargs.setdefault('infra_step', True)
    kwargs.setdefault('step_test_data',
                      self.test_api.step_test_data_factory('my-footer'))
    result = self.m.python(
        'read git footers', self.m.depot_tools.root.join('git_footers.py'),
        args, stdout=self.m.raw_io.output(), ok_ret=(0,1), **kwargs)

    if result.retcode == 1:
      return None
    return [l.strip() for l in result.stdout.splitlines() if l.strip()]

  def from_message(self, message, key=None, **kwargs):
    """Return the footer value(s) in the commit message for the given key.

    Args:
      message (str): The git commit message.
      key (str): The footer key to look for. If not set, returns all footers
          found in the message. Note that if this parameter is set, it is
          EXCLUDED from the returned footer string(s). If it is not set, the
          footers are formatted as '<key>:<value>'.

    Returns:
      list[str]: The footer value(s) found in the commit message.
    """
    assert 'stdin' not in kwargs, 'cannot set stdin on from_message'
    args = []
    if key is not None:
      args.extend(['--key', key])
      kwargs.setdefault(
          'step_test_data',
          self.test_api.step_test_data_factory('%s:%s' % (message, key)))
    return self(*args, stdin=self.m.raw_io.input_text(message), **kwargs)

  def from_ref(self, ref, key=None, **kwargs):
    """Return the footer value(s) in the given ref for the given key.

    Args:
      ref (str): The git ref.
      key (str): The footer key to look for. See from_message docstring.

    Returns:
      list[str]: The footer value(s) found in the ref's commit message.
    """
    args = [ref]
    if key is not None:
      args.extend(['--key', key])
      kwargs.setdefault(
         'step_test_data',
          self.test_api.step_test_data_factory('%s:%s' % (ref, key)))
    return self(*args, **kwargs)

  def position_num(self, ref, **kwargs):
    """Return the footer value for Cr-Commit-Position.

    Args:
      ref (str): The git ref.

    Returns:
      list[str]: The position number for the ref.
    """
    kwargs.setdefault('step_test_data',
                      self.test_api.step_test_data_factory('101'))
    output = self(ref, '--position-num', **kwargs)
    if not output:
      return 1

    assert len(output) == 1, 'expected exactly one Cr-Commit-Position footer'
    return int(output[0].strip())
