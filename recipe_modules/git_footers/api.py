# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the git_footers script.."""

from typing import List, Set

from PB.chromiumos import common as common_pb2
from recipe_engine import recipe_api


class GitFootersApi(recipe_api.RecipeApi):
  """A module for calling git_footers."""

  def __call__(self, *args, **kwargs):
    """Call git_footers.py with the given args.

    Args:
      args: Arguments for git_footers.py
      kwargs: Keyword arguments for python call.

    Returns:
      list[str]: All matching footer values, or None
    """
    kwargs.setdefault('infra_step', True)
    kwargs.setdefault('step_test_data',
                      self.test_api.step_test_data_factory('my-footer'))
    result = self.m.step(
        'read git footers',
        ['vpython3', self.m.depot_tools.root / 'git_footers.py'] + list(args),
        stdout=self.m.raw_io.output(), ok_ret=(0, 1), **kwargs)

    if result.retcode == 1:
      return None
    stdout = result.stdout.decode()
    return [l.strip() for l in stdout.splitlines() if l.strip()]

  def from_gerrit_change(self, gerrit_change, key=None, memoize=True, **kwargs):
    """Return the footer value(s) in the commit message for the given key.


    Args:
      gerrit_change (GerritChange): The change of interest.
      key (str): The footer key to look for. If not set, returns all footers
          found in the Gerrit change message. Note that if this parameter is
          set, it is EXCLUDED from the returned footer string(s). If it is not
          set, the footers are formatted as '<key>:<value>'.
      memoize (bool): Should we memoize the call (default: True).

    Returns:
      list[str]: The footer value(s) found in the commit message.
    """
    message_text = self.m.gerrit.get_change_description(gerrit_change,
                                                        memoize=memoize)
    return self.from_message(message_text, key=key, **kwargs)

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

  def position_ref(self, ref, test_position_ref=None, **kwargs):
    """Return the footer ref for Cr-Commit-Position.

    Args:
      ref (str): The git ref.
      test_position_ref (int): The test value.  step_test_data, if given, will
        override this.
      **kwargs (dict): positional parameters for self.__call__()

    Returns:
      str: The position ref for the ref.
    """
    test_position_ref = (
        self.test_api.test_position_ref
        if test_position_ref is None else test_position_ref)
    kwargs.setdefault(
        'step_test_data',
        self.test_api.step_test_data_factory(str(test_position_ref)))
    output = self(ref, '--position-ref', **kwargs)

    assert len(output) == 1, 'expected exactly one Cr-Commit-Position footer'
    return output[0].strip()

  def position_num(self, ref, test_position_num=None, **kwargs):
    """Return the footer value for Cr-Commit-Position.

    Args:
      ref (str): The git ref.
      test_position_num (int): The test value.  step_test_data, if given, will
        override this.
      **kwargs (dict): positional parameters for self.__call__()

    Returns:
      list[str]: The position number for the ref.
    """
    test_position_num = (
        self.test_api.test_position_num
        if test_position_num is None else test_position_num)
    kwargs.setdefault(
        'step_test_data',
        self.test_api.step_test_data_factory(str(test_position_num)))
    output = self(ref, '--position-num', **kwargs)
    if not output:
      # While we would like to fail here, if we are running on an unpinned
      # manifest, we may not find a position.  See crbug/1170601.
      return 1

    assert len(output) == 1, 'expected exactly one Cr-Commit-Position footer'
    return int(output[0].strip())

  def edit_add_change_description(self, change_message, footer, footer_text):
    """Edit or add the given footer to the change_message.

    Args:
      change_message (str): The gerrit change message.
      footer (str): The name of the footer, e.g. "Cq-Depends"
      footer_text (str): The value of the footer. If footer_text starts with
        "{footer}: ", that prefix will be ignored.

    Returns:
      str: Modified change_message.
    """
    blocks = change_message.split('\n\n')
    footer_block = blocks[-1]
    footers = footer_block.split('\n')

    def reassemble():
      blocks[-1] = '\n'.join(footers)
      return '\n\n'.join(blocks)

    if footer_text.startswith(footer + ':'):
      footer_text = footer_text[len(footer) + 1:].lstrip()
    new_footer = '{}: {}'.format(footer, footer_text)
    for i, _ in enumerate(footers):
      # Exists, edit existing footer.
      if footers[i].startswith(footer):
        footers[i] = new_footer
        return reassemble()
    # Doesn't exist, add to start of footer block.
    footers = [new_footer] + footers
    return reassemble()

  def get_footer_values(self, gerrit_changes: List[common_pb2.GerritChange],
                        key: str, **kwargs) -> Set[str]:
    """Gets a list of values from a footer.

    Fetches the named footer from the gerrit changes, and returns a set of all
    of the (comma-separated) values found.

    Args:
      gerrit_changes: Gerrit changes applied to this run.
      key: The footer name (key) to fetch.
      kwargs: Other keyword arguments, passed to git_footers.from_gerrit_change.

    Returns:
      values: A set of values found for the given key.  May be empty.
    """
    ret = set()
    for gerrit_change in gerrit_changes:
      values = self.from_gerrit_change(gerrit_change, key=key, **kwargs)
      ret.update(x.strip() for v in values for x in v.split(','))
    return ret
