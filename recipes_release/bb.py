#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for interacting with builds / builders / buildbucket."""

from collections import defaultdict
import concurrent.futures
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

  if recipes_version is None:
    return None

  return recipes_version


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

  recipe_by_builder = {}
  # Recipes used by sentinel builders.
  for builder in builders:
    recipe_by_builder[builder] = get_builder_recipe(builder)

  relevant_builders = set()
  if changes:
    affected_recipes = get_affected_recipes(changes[0], changes[-1],
                                            list(recipe_by_builder.values()))
    for builder, recipe in recipe_by_builder.items():
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
          change, change, list(recipe_by_builder.values()))
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


def check_recent_build_statuses(
    builder: str,
    exemptions: List[Callable[[Dict[str, Any]], bool]],
    pending_changes: List[git.Commit],
    diff_fn: Callable[[git.Commit], List[str]],
) -> bool:
  """Check whether a single builder has had any recent non-successes."""
  builds = _bb_ls('-status', 'ended', '-n', '5', '-A', builder)

  found_statuses = set()
  githashes = []

  for build in builds:
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
    if change.is_older_than(most_recent_githash):
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


def _bb_ls(*args) -> List[Dict]:
  cmd = ['bb', 'ls', '-json'] + list(args)
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)
  builds = []
  for line in p.stdout.split('\n'):
    if not line:
      continue
    builds.append(json.loads(line))
  return builds


def determine_maximum_covered_instance(
    changes: List[git.Commit], checks: Tuple[staging_checks.StagingReCheck],
    verbose: bool = False) -> common.CipdInstance:
  """Determine the maximum covered recipes instance.

  The maximum covered recipes instance is the most recent instance / change
  that has N runs of each staging builder.

  It does so as follows:
  * For each builder,
    * Fetch all build results since the oldest commit landed.
    * Iterate through the changes from newest to oldest, build a map mapping
      change to the number of builds covering that change.
  * For each change (oldest to newest),
    * Check that there are N runs of each relevant staging builder.
  * Return the newest change that has full coverage.

  Args:
    changes: The changes pending release.
    checks: The staging checks used to qualify a release.
    verbose: If set, more information is logged.
  Returns:
    The most recent CIPD instance that had adequate coverage in staging.
  """
  builders = set()
  for re_check in checks:
    builders.update(
        return_builders_for_regex(re_check.project, re_check.bucket,
                                  re_check.regex))

  # TODO(b/287276108): Remove N=5 hardcode.
  REQUIRED_BUILDER_COUNT = 5

  recipe_by_builder = {}
  # Recipes used by sentinel builders.
  for builder in builders:
    recipe_by_builder[builder] = get_builder_recipe(builder)

  # `changes` is ordered newest to oldest.
  # We can use commit_timestamp as a key even though it's a string
  # since it's ISO8601.
  changes = sorted(changes, key=lambda change: change.commit_timestamp,
                   reverse=True)
  change_coverage_per_build = defaultdict(lambda: {})

  def print_if_verbose(*args):
    if verbose:
      print(*args)

  def get_change_coverage(builder: str) -> List[int]:
    """Determine the number of builds of `builder` covering each change in
    `changes`.

    This method is separate so that it can be called in parallel for multiple
    builders.

    Returns:
      List corresponding to `changes` where the ith element is the number
      of builds covering changes[i].
    """
    # Get all build results since the oldest pending change.
    project, bucket, builder_name = tuple(builder.split('/'))
    predicate = {
        'builder': {
            'project': project,
            'bucket': bucket,
            'builder': builder_name,
        },
        'status': 'ENDED_MASK',
        'create_time': {
            'start_time': changes[-1].commit_timestamp,
        },
    }
    builds = _bb_ls('-predicate', json.dumps(predicate), '-fields', 'infra')

    # If there are no builds for the builder at all, don't let that be a blocker.
    if len(builds) < REQUIRED_BUILDER_COUNT:
      if len(
          _bb_ls('-fields', 'id', builder, '-n',
                 str(REQUIRED_BUILDER_COUNT))) < REQUIRED_BUILDER_COUNT:
        print_if_verbose(
            f'<{REQUIRED_BUILDER_COUNT} build results for {builder}, it must be new. Skipping.'
        )
        return [REQUIRED_BUILDER_COUNT] * len(changes)

    print_if_verbose(
        f'Found {len(builds)} builds for {builder} since {changes[-1].hash}.')

    # change_coverage contains the number of builds that ran each change.
    change_coverage = [0] * len(changes)

    # We calculate change_coverage for a builder as follows:
    # Maintain a pointer to the current change (starts at the newest change).
    # Step through the builds, newest to oldest.
    # If the builder ran the current change, increment change_coverage for that change.
    # Otherwise, advance the change pointer until we reach a change that was covered by this buuld.
    change_pointer = 0
    build_pointer = 0
    # `bb ls` are ordered newest to oldest.
    while build_pointer < len(builds):
      build = builds[build_pointer]
      cipd_version = build_to_cipd_version(build)
      # If there's no cipd_version we can't use this build result.
      if not cipd_version:
        build_pointer += 1
        continue

      # Stop looking once we have sufficient coverage to reduce runtime.
      if change_coverage[change_pointer] >= REQUIRED_BUILDER_COUNT:
        for j in range(change_pointer + 1, len(changes)):
          change_coverage[j] = change_coverage[change_pointer]
        break

      githash = cipd.cipd_version_to_githash(cipd_version)
      # If the change commit is older than the one the build ran, we got
      # coverage. Look at the next build result.
      if changes[change_pointer].hash == githash or changes[
          change_pointer].is_older_than(githash):
        change_coverage[change_pointer] += 1
        build_pointer += 1
      # If we're on the last change we can exit.
      elif change_pointer == len(changes) - 1:
        break
      # If the build didn't include this change, start considering the next
      # (older) change. All builds that covered the current change necessarily
      # covered the next one.
      else:
        change_coverage[change_pointer + 1] = change_coverage[change_pointer]
        change_pointer += 1
    return change_coverage

  # Get change coverage for each builder. Multithread for performance.
  with concurrent.futures.ThreadPoolExecutor() as executor:
    for builder in builders:
      change_coverage_per_build[builder] = executor.submit(
          get_change_coverage, builder)

  # Collect results. Re-order so the oldest change is first.
  for builder in change_coverage_per_build:
    change_coverage_per_build[builder] = change_coverage_per_build[
        builder].result()[::-1]
  changes = changes[::-1]

  last_covered_change = None
  for i, change in enumerate(changes):
    # Less confusing for humans if we don't use a trivial change for release.
    if change.trivial:
      continue

    print_if_verbose(f'Considering commit {change.hash}')

    affected_recipes = get_affected_recipes(
        change, change, list(set(recipe_by_builder.values())))

    missing_coverage = False
    for builder in builders:
      # Make sure we have sufficient coverage for all relevant builders.
      # Chromite Pin Uprevs return nothing for ./recipes.py analyze, so we
      # need to enforce coverage for all builders.
      if not change.chromite_pin_uprev and recipe_by_builder[
          builder] not in affected_recipes:
        continue
      if change_coverage_per_build[builder][i] < REQUIRED_BUILDER_COUNT:
        print_if_verbose(
            f'{change.hash} lacking coverage in {builder} ({change_coverage_per_build[builder][i]}/{REQUIRED_BUILDER_COUNT} builds).'
        )
        missing_coverage = True
        break
    if missing_coverage:
      break
    print_if_verbose(f'Commit {change.hash} is releasable.')
    last_covered_change = change

  if last_covered_change:
    return last_covered_change.get_cipd_instance()
  return None
