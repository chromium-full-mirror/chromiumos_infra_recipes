#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for interacting with builds / builders / buildbucket."""

from functools import lru_cache
import json
import re
import subprocess
import sys
import tempfile
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import cipd
import common
import git
import staging_checks

MIN_BRANCH_MILESTONE = 113


@lru_cache(maxsize=None)
def _get_affected_recipes(newest_change: git.Commit, oldest_change: git.Commit,
                          recipes: str) -> List[str]:
  """Internal (cachable) function for get_affected_recipes."""
  recipes = sorted(recipes.split(','))

  cmd = [
      'git', 'diff', '--name-only', newest_change.hash, f'{oldest_change.hash}~'
  ]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)
  affected_files = p.stdout.strip().split()

  with tempfile.NamedTemporaryFile(mode='w') as input_file, \
        tempfile.NamedTemporaryFile() as output_file:
    json.dump(
        {
            'files': affected_files,
            'recipes': recipes,
        },
        input_file,
    )
    input_file.flush()

    cmd = ['./recipes.py', 'analyze', input_file.name, output_file.name]
    subprocess.run(cmd, capture_output=True, check=True)

    data = json.loads(output_file.read())

  return data['recipes']


def get_affected_recipes(newest_change: git.Commit, oldest_change: git.Commit,
                         recipes: List[str]) -> List[str]:
  """Get the list of recipes affected by the given commits.

  Args:
    newest_change: The most recent change being proposed for release.
    oldest_change: The oldest change being proposed for release.
    recipes: List of recipes used by the staging builders. Required arg for
      `./recipes.py analyze`.
  """
  return _get_affected_recipes(newest_change, oldest_change,
                               ','.join(sorted(recipes)))


@lru_cache(maxsize=None)
def get_builder_recipe(builder: str):
  """Get the recipe used by the given builder."""
  cmd = ['led', 'get-builder', builder]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)
  builder_data = json.loads(p.stdout)
  return builder_data['buildbucket']['bbagent_args']['build']['input'][
      'properties']['recipe']


def get_builder_link(builder: str) -> str:
  if not builder.startswith('chromeos/staging/'):
    raise ValueError(
        f"expected builder to start with 'chromeos/staging', got {builder}")

  builder_name = builder.replace('chromeos/staging/', '', 1)
  return f'https://ci.chromium.org/p/chromeos/builders/staging/{builder_name}'


def check_staging_builders(changes: List[git.Commit],
                           checks: Tuple[staging_checks.StagingReCheck],
                           ignore_failures: bool = False):
  """Check for failures in staging builders. Quit early if any problems."""
  print('=== Check staging status ===')
  print('Determining relevancy of each staging builder...')
  builders = []
  for re_check in checks:
    builders.extend(
        return_builders_for_regex(re_check.project, re_check.bucket,
                                  re_check.regex))

  builder_recipes = {}
  # Recipes used by sentinel builders.
  for builder in builders:
    builder_recipes[builder] = get_builder_recipe(builder)

  relevant_builders = set()
  if changes:
    affected_recipes = get_affected_recipes(changes[0], changes[-1],
                                            list(builder_recipes.values()))
    for builder, recipe in builder_recipes.items():
      if recipe in affected_recipes:
        relevant_builders.add(builder)
    irrelevant_builders = set(builders) - relevant_builders
    if irrelevant_builders:
      print('Irrelevant builders: ', ', '.join(sorted(irrelevant_builders)))

  baddies = []
  print('Looking for 5 consecutive successes in staging...')
  for re_check in checks:
    builders = return_builders_for_regex(re_check.project, re_check.bucket,
                                         re_check.regex)
    for builder in filter(lambda b: b in relevant_builders, builders):
      diff_fn = lambda change: get_affected_recipes(
          change, change, list(builder_recipes.values()))
      if check_recent_build_statuses(builder, re_check.exemptions, changes,
                                     diff_fn):
        baddies.append(builder)

  if baddies:
    if ignore_failures:
      print('Ignoring failures, as requested.')
    else:
      print('Please address the failures in the above builders.')
      print('When you\'re certain staging is OK, you may use -s to continue.')
      sys.exit(1)
  print()


def build_to_cipd_version(
    build: Dict[str, Any]) -> Optional[common.CipdVersion]:
  """Return the resolved recipes version used by the build.

  In cases where there is no resolved recipes version, e.g. bbagent doesn't
  start, return None.
  """

  try:
    specs = build['infra']['buildbucket']['agent']['output']['resolvedData'][
        'kitchen-checkout']['cipd']['specs']
  except KeyError:
    return None

  recipes_version = None
  for spec in specs:
    if spec['package'] == common.RECIPE_BUNDLE:
      recipes_version = spec['version']

  if not recipes_version:
    raise ValueError(
        f"resolved recipes version not found for build {build['builder']['builder']}"
    )

  return recipes_version


def check_recent_build_statuses(
    builder: str,
    exemptions: List[Callable[[Dict[str, Any]], bool]],
    pending_changes: List[git.Commit],
    diff_fn: Callable[[git.Commit], List[str]],
) -> bool:
  """Check whether a single builder has had any recent non-successes."""
  cmd = ['bb', 'ls', '-status', 'ended', '-n', '5', '-json', '-A', builder]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)

  found_statuses = set()
  githashes = []
  for line in p.stdout.split('\n'):
    if not line:
      continue
    build = json.loads(line)
    status = build['status']
    # Shouldn't be necessary because of `-status ended`, but better safe than
    # sorry.
    if status in ('STARTED', 'SCHEDULED'):
      continue

    # INFRA_FAILUREs should never be ignored.
    if status != 'INFRA_FAILURE':
      for exemption in exemptions:
        if exemption(build):
          status = 'OK_FAILURE'

    found_statuses.add(status)
    cipd_version = build_to_cipd_version(build)
    if cipd_version:
      githashes.append(cipd.cipd_version_to_githash(cipd_version))

  if not found_statuses:
    print(f'No runs recorded for: {builder}')
    return True

  if not githashes:
    print(
        f'No runs for builder {builder} had resolved recipes versions, likely due to infra failures'
    )
    return False

  # Count the number of non-trivial changes since the last build.
  most_recent_githash = githashes[0]
  non_trivial_changes_since_most_recent_build = []
  for change in pending_changes:
    if git.is_older_than(change.hash, most_recent_githash):
      break

    if not change.trivial:
      non_trivial_changes_since_most_recent_build.append(change)

  num_non_trivial_changes_since_most_recent_build = len(
      non_trivial_changes_since_most_recent_build)

  success = set(found_statuses).issubset({'SUCCESS', 'OK_FAILURE'})
  success_str = f'{common.BOLDGREEN}Success{common.RESET}' if success else f'{common.BOLDRED}Non-success{common.RESET}'
  status_str = f'{success_str}: {get_builder_link(builder)} --> {", ".join(sorted(list(found_statuses)))}'

  relevant_changes = []
  builder_recipe = get_builder_recipe(builder)
  for change in non_trivial_changes_since_most_recent_build:
    affected_files = diff_fn(change)
    if builder_recipe in affected_files:
      relevant_changes.append(change)

  # If there have been changes since the most recent build, add a line to the
  # status.
  if num_non_trivial_changes_since_most_recent_build:
    changes_str = 'change' if num_non_trivial_changes_since_most_recent_build == 1 else 'changes'
    relevant_str = f' ({len(relevant_changes)} relevant)'
    status_str += f'\n  {num_non_trivial_changes_since_most_recent_build} {changes_str} since last build{relevant_str}, '

    non_trivial_pending_changes = list(
        filter(lambda c: not c.trivial, pending_changes))

    # If a non-trivial change was included since the last release, print the
    # last hash.
    if num_non_trivial_changes_since_most_recent_build < len(
        non_trivial_pending_changes):
      status_str += (
          'last built commit was '
          f'{common.BOLDBLUE}{non_trivial_pending_changes[num_non_trivial_changes_since_most_recent_build].short_hash}{common.RESET}'
      )
    else:
      status_str += 'builder has not been run since last release'

  if not success or (num_non_trivial_changes_since_most_recent_build and
                     relevant_changes):
    print(status_str)

  return not success


@lru_cache(maxsize=None)
def _call_bb_builders(cmd):
  return subprocess.run(cmd, capture_output=True, text=True, check=True)


def return_builders_for_regex(project: str, bucket: str,
                              regex: str) -> List[str]:
  """Return the list of builders matching a certain regex."""
  r = re.compile(regex)
  cmd = ('bb', 'builders', '/'.join((project, bucket)))
  p = _call_bb_builders(cmd)

  ret = []
  for line in p.stdout.split('\n'):
    if not line:
      continue
    builder = line.strip().split('/')[-1]
    s = r.fullmatch(builder)
    if s:
      gd = s.groupdict()
      if 'milestone' in gd and int(gd['milestone']) < MIN_BRANCH_MILESTONE:
        continue
      ret.append(line.strip())
  return ret
