#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for working with commits / git."""

from datetime import datetime
from functools import lru_cache
from functools import total_ordering
import re
import subprocess
from typing import List

import common
from protos.recipes_autoreleaser import ReleaseResult  #pylint: disable=no-name-in-module

RE_TRIVIAL_COMMIT = re.compile(r'Roll recipe.*\(trivial\)\.?$')
MISSING_INSTANCE = '---------COULD_NOT_FIND_INSTANCE--------'


@total_ordering
class Commit:

  def __init__(self, git_hash, username, message, human_readable_commit_date,
               commit_timestamp: str):
    self.hash = git_hash
    self.username = username
    self.message = message
    self.human_readable_commit_date = human_readable_commit_date
    self.commit_timestamp = datetime.fromisoformat(commit_timestamp)

  def __hash__(self):
    return hash(self.hash)

  def __eq__(self, other):
    return self.hash == other.hash

  def __lt__(self, other):
    # We can use commit_timestamp as a key even though it's a string
    # since it's ISO8601.
    return self.commit_timestamp < other.commit_timestamp

  @property
  def short_hash(self):
    return self.hash[:9]

  @property
  def trivial(self):
    return RE_TRIVIAL_COMMIT.match(self.message)

  def get_cipd_instance(self) -> str:
    """Find the recipe bundle instance that contains up to this commit."""
    return _get_cipd_instance(self)

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
        f'{common.BOLDBLUE}{self.short_hash}', self.human_readable_commit_date,
        f'{common.BOLDGREEN}[{self.username}] ', f'{common.RESET}{self.message}'
    ]
    if show_instances:
      strs = [self.get_cipd_instance()] + strs

    return strs

  def plain_strs(self) -> List[str]:
    """Return plain strings for each field of the Commit.

    Intended for use with the tabulate library, which takes a list of lists and
    aligns them into a table. For example

    ```
    print(tabulate([c.plain_strs() for c in commits]))
    ```

    Returns:
      A list of strings for use with tabulate.
    """
    return [self.short_hash, f'[{self.username}]', self.message]

  def is_older_than(self, other_hash: str) -> bool:
    """Return whether the change is older than another hash."""
    return _is_older_than(self.hash, other_hash)

  def to_proto(self) -> ReleaseResult.GitCommit:
    """Return a GitCommit proto based on this Commit."""
    return ReleaseResult.GitCommit(
        hash=self.hash,
        author=self.username,
        subject=self.message,
        relative_date=self.human_readable_commit_date,
        cipd_instance=self.get_cipd_instance(),
    )


@lru_cache(maxsize=None)
def _get_cipd_instance(commit: Commit) -> str:
  """Find the recipe bundle instance that contains up to this commit."""
  tag = f'git_revision:{commit.hash}'
  cmd = ['cipd', 'search', common.RECIPE_BUNDLE, '-tag', tag]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)

  for line in [line.strip() for line in p.stdout.split('\n')]:
    if line.startswith(common.RECIPE_BUNDLE):
      return line.split(':')[1]
  return MISSING_INSTANCE


@lru_cache(maxsize=None)
def _is_older_than(maybe_older_hash: str, commit_hash: str) -> bool:
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
  """Find all changes in the range (from_hash, to_hash].

  from_hash is not inclusive, to_hash is inclusive. I.e. finds the changes
  between the first change following from_hash to to_hash.

  Args:
    recipes_dir: The recipes dir to work in.
    from_hash: The git hash immediately preceding the first in the changelist.
    to_hash: The final git hash of the changelist.
  Returns:
    The changes that will be released, ordered from newest to oldest.
  """
  fmt = '%H|%al|%s|%cr|%cI'  # %H=commit, %al=user, %s=summary, %cr=commit date, %cI=ISO 8061 commit timestamp
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
    commit_hash, commit_user, commit_message, commit_date, commit_timestamp = line.split(
        '|')
    changes.append(
        Commit(commit_hash, commit_user, commit_message, commit_date,
               commit_timestamp))
  return changes


def trim_trivial_suffix(changes: List[Commit]) -> List[Commit]:
  """Remove any trivial commits that have landed since the last non-trivial commit.

  Args:
    changes: Commits to trim, order does not matter.

  Returns:
    Trimmed changes, sorted from oldest to newest.
  """
  # Sort changes newest to oldest.
  changes = sorted(changes, reverse=True)
  for i, change in enumerate(changes):
    if not change.trivial:
      return changes[i:][::-1]
  return []
