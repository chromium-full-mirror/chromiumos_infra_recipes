#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for dealing with commits / git."""

from functools import lru_cache
import re
import subprocess
from typing import List

import common

RE_TRIVIAL_COMMIT = re.compile(r'Roll recipe.*\(trivial\)\.?$')


class Commit:

  def __init__(self, git_hash, username, message, date):
    self.hash = git_hash
    self.username = username
    self.message = message
    self.cipd_instance = None
    self.date = date

  @property
  def short_hash(self):
    return self.hash[:9]

  @property
  def trivial(self):
    return RE_TRIVIAL_COMMIT.match(self.message)

  def get_cipd_instance(self) -> str:
    """Find the recipe bundle instance that contains up to this commit."""
    tag = f'git_revision:{self.hash}'
    cmd = ['cipd', 'search', common.RECIPE_BUNDLE, '-tag', tag]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)

    for line in [line.strip() for line in p.stdout.split('\n')]:
      if line.startswith(common.RECIPE_BUNDLE):
        return line.split(':')[1]
    return '---------COULD_NOT_FIND_INSTANCE--------'

  def set_cipd_instance(self, instanceid: common.CipdInstance):
    self.cipd_instance = instanceid

  def color_strs(self, show_instances: bool) -> List[str]:
    """Return colorified strings for each field of the Commit.

    Intended for use with the tabulate library, which takes a list of lists and
    aligns them into a table. For example

    ```
    print(tabulate([c.color_strs() for c in commits]))
    ```

    Args:
      show_instances: If true, include the CIPD instance.

    Returns:
      A list of strings for use with tabulate.
    """
    strs = [
        f'{common.BOLDBLUE}{self.short_hash}', self.date,
        f'{common.BOLDGREEN}[{self.username}] ', f'{common.RESET}{self.message}'
    ]
    if show_instances:
      strs = [self.get_cipd_instance()] + strs

    return strs

  def plain_strs(self, with_bullet: bool = False) -> str:
    """Return plain strings for each field of the Commit.

    Intended for use with the tabulate library, which takes a list of lists and
    aligns them into a table. For example

    ```
    print(tabulate([c.plain_strs() for c in commits]))
    ```

    Args:
      with_bullet: If true, prefix with a '*'.

    Returns:
      A list of strings for use with tabulate.
    """
    strs = [self.short_hash, f'[{self.username}]', self.message]
    if with_bullet:
      strs = ['*'] + strs
    return strs


@lru_cache(maxsize=None)
def is_older_than(maybe_older_hash: str, commit_hash: str) -> bool:
  """Determines if one commit is older (i.e. is an ancestor) of the other."""
  cmd = ['git', 'merge-base', '--is-ancestor', maybe_older_hash, commit_hash]
  p = subprocess.run(cmd, capture_output=True, text=True)  #pylint: disable=subprocess-run-check
  if p.returncode == 0:
    return True
  if p.returncode == 1:
    return False
  raise Exception(f'error calling `{" ".join(cmd)}`: {p.stderr}')


def get_pending_changes(recipes_dir: str, from_hash: common.GitHash,
                        to_hash: common.GitHash) -> List[Commit]:
  """Find all changes that will be released.

  recipes_dir: The recipes dir to work in.
  from_hash: The git hash immediately preceding the first in the changelist.
  to_hash: The final git hash of the changelist.
  verbose: If False, exclude trivial recipe rolls.
  """
  print('=== Checking for pending changes ===')
  print('Here are the changes from the provided (or default main) environment:')
  fmt = '%H|%al|%s|%cr'  # %H=commit, %al=user, %s=summary, %ch=commit date
  cmd = [
      'git', 'log', '--graph', f'--pretty=format:{fmt}',
      f'{from_hash}..{to_hash}'
  ]
  p = subprocess.run(cmd, capture_output=True, text=True, cwd=recipes_dir,
                     check=True)
  lines = [line.strip().lstrip('* ') for line in p.stdout.split('\n')]
  changes = []
  for line in lines:
    if not line:
      continue
    commit_hash, commit_user, commit_message, commit_date = line.split('|')
    changes.append(
        Commit(commit_hash, commit_user, commit_message, commit_date))
  return changes
