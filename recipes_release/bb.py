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
import tempfile
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from dateutil import parser

import cipd
import common
import git
import staging_checks

MIN_BRANCH_MILESTONE = 113


@lru_cache(maxsize=None)
def _get_affected_recipes(changes: Tuple[git.Commit],
                          recipes: str) -> List[str]:
  """Internal (cachable) function for get_affected_recipes."""
  recipes = sorted(recipes.split(','))

  changes = sorted(changes, reverse=True)
  newest_change = changes[0]
  oldest_change = changes[-1]

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


def get_affected_recipes(changes: List[git.Commit],
                         recipes: List[str]) -> List[str]:
  """Get the list of recipes affected by the given commits.

  Args:
    changes: The changes being propsed for release.
    recipes: List of recipes used by the staging builders. Required arg for
      `./recipes.py analyze`.
  """
  return _get_affected_recipes(tuple(changes), ','.join(sorted(recipes)))


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


@lru_cache(maxsize=None)
def return_builders_for_regex(project: str, bucket: str,
                              regex: str) -> List[str]:
  """Return the list of builders matching a certain regex."""
  r = re.compile(regex)
  cmd = ('bb', 'builders', '/'.join((project, bucket)))
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)

  ret = []
  for line in p.stdout.split('\n'):
    if not line:
      continue
    builder = line.strip().split('/')[-1]
    match = r.fullmatch(builder)
    if match:
      gd = match.groupdict()
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


Build = Dict[str, Any]


class Builds:
  """Stores all the relevant builds for all the relevant builders."""

  def __init__(self):
    # Maps 'builder' name to list of builds.
    self._data: Dict[str, List[Build]] = {}

  def _parse_build_timestamps(self):
    for builder in self._data.keys():
      for i, build in enumerate(self._data[builder]):
        self._data[builder][i]['createTime'] = parser.parse(build['createTime'])

  def initialize(self, checks: Tuple[staging_checks.StagingReCheck],
                 changes: List[git.Commit], verbose: bool = False):
    earliest_change = min(changes)

    builders = []
    for re_check in checks:
      builders.extend(
          return_builders_for_regex(re_check.project, re_check.bucket,
                                    re_check.regex))
    results = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
      for builder, builds in zip(
          builders,
          executor.map(
              lambda builder: self._get_builds_after_change(
                  builder, earliest_change), builders)):
        # Collect results.
        results[builder] = builds
        if verbose:
          print(
              f'Found {len(results[builder]):3} builds for {builder} since {earliest_change.hash}.'
          )

    self._data = results
    self._parse_build_timestamps()

  def initialize_with_test_data(self, data: Dict[str, List[Build]]):
    self._data = data
    self._parse_build_timestamps()

  def _get_builds_after_change(self, builder: str,
                               change: git.Commit) -> List[Build]:
    project, bucket, builder_name = tuple(builder.split('/'))
    predicate = {
        'builder': {
            'project': project,
            'bucket': bucket,
            'builder': builder_name,
        },
        'status': 'ENDED_MASK',
        'create_time': {
            'start_time': change.commit_timestamp.isoformat(),
        },
    }
    fields = [
        'id', 'status', 'create_time', 'infra', 'summary_markdown',
        'cancellation_markdown'
    ]
    # Need input properties for `atlas_signingnext_exemption`, optimize
    # by only fetching them for paygen builders.
    if 'paygen' in builder_name:
      fields.append('input')
    args = ['-fields', ','.join(fields)]
    return _bb_ls('-predicate', json.dumps(predicate), *args)

  def get_builds_for(self, builder: str) -> List[Build]:
    """Get all build results for the given builder."""
    return self._data.get(builder, [])

  def get_builds_after(self, builder: str, change: git.Commit):
    """Get all build results since the given change landed, sorted oldest to newest."""
    builds = self.get_builds_for(builder)
    # Sorts oldest to newest.
    builds = sorted(builds, key=lambda build: build['createTime'])

    for i, build in enumerate(builds):
      if build['createTime'] >= change.commit_timestamp:
        return builds[i:]
    return []

  def get_builds_containing(self, builder: str, change: git.Commit):
    """Get all build results that ran with the given change, sorted oldest to newest."""
    # Sort builds oldest to newest.
    builds = self.get_builds_after(builder, change)
    # Filter out builds missing a CIPD version, those aren't usable.
    builds = list(
        filter(lambda build: build_to_cipd_version(build) is not None, builds))

    for i, build in enumerate(builds):
      cipd_version = build_to_cipd_version(build)
      githash = cipd.cipd_version_to_githash(cipd_version)
      # If the change commit is older than the one the build ran, we've found our suffix
      # of builds.
      if change.hash == githash or change.is_older_than(githash):
        return builds[i:]
    return []


def check_staging_builders(all_builds: Builds, changes: List[git.Commit],
                           checks: Tuple[staging_checks.StagingReCheck],
                           ok_fewer: List[str],
                           log_messages: bool = False) -> List[str]:
  """Check for failures in staging builders.

  Args:
    all_builds: All relevant build results as calculated at startup.
    changes: Changes under question.
    checks: Staging checks to use to validate a release.
    ok_fewer: List of builders for which it's OK to have fewer than N builds
      (as configured in `checks`).
    log_messages: Whether to log to stdout.

  Returns:
    List of builders with issues.
  """

  def print_if(*args, **kwargs):
    if log_messages:
      print(*args, **kwargs)

  print_if('Determining relevancy of each staging builder...')
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
    affected_recipes = get_affected_recipes(changes,
                                            list(recipe_by_builder.values()))
    for builder, recipe in recipe_by_builder.items():
      if recipe in affected_recipes:
        relevant_builders.add(builder)
    irrelevant_builders = set(builders) - relevant_builders
    if irrelevant_builders:
      print_if('Irrelevant builders: ', ', '.join(sorted(irrelevant_builders)))

  baddies = []
  print_if('Looking for consecutive successes in staging...')
  for re_check in checks:
    builders = return_builders_for_regex(re_check.project, re_check.bucket,
                                         re_check.regex)
    for builder in filter(lambda b: b in relevant_builders, builders):
      not_ok, status_str = check_recent_build_statuses(
          all_builds, builder, re_check.exemptions, changes,
          re_check.num_builds, ok_fewer=builder in ok_fewer)
      if not_ok:
        print_if(status_str)
        baddies.append(builder)
  return baddies


def check_recent_build_statuses(
    all_builds: Builds,
    builder: str,
    exemptions: List[Callable[[Dict[str, Any]], bool]],
    pending_changes: List[git.Commit],
    num_builds_needed: int,
    ok_fewer: bool = False,
) -> Tuple[bool, str]:
  """Check whether a single builder has had any recent non-successes.

  Args:
    all_builds: All relevant build results as calculated at startup.
    builder: The builder to check.
    exemptions: Exemptions for known (acceptable) build failures.
    pending_changes: Changes under question.
    num_builds_needed: The number of builds required to validate the changes.
    ok_fewer: Whether it's OK to have fewer than `num_builds_newer` (e.g. if
      the builder is newly defined).

  Returns:
    (bool) Whether there is an issue with the builder.
    (str) An error string.
  """
  builds = all_builds.get_builds_containing(builder, max(pending_changes))
  # Sort oldest to newest.
  # createTime is of the form "2023-07-14T17:00:03.592856413Z", so fine to sort
  # by the raw string.
  builds = sorted(builds, key=lambda build: build['createTime'])

  found_statuses = []
  good_builds = 0
  bad_build_ids = []

  for build in builds[:num_builds_needed]:
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

    found_statuses.append(status)
    if status in ['SUCCESS', 'OK_FAILURE']:
      good_builds += 1
    else:
      bad_build_ids.append(f'go/bbid/{build["id"]}')

  success = True
  problem_str = ''

  # Everything was a success, we just didn't have enough builds.
  if set(found_statuses).issubset({'SUCCESS', 'OK_FAILURE'}):
    if not (good_builds >= num_builds_needed or ok_fewer):
      success = False
      problem_str = f'Needed {num_builds_needed} consecutive good builds, only {good_builds} (good) builds available.'
  else:
    success = False
    problem_str = f'Needed {num_builds_needed} consecutive good builds, found failures. Statuses: {", ".join(sorted(list(found_statuses)))} '
    problem_str += f'Sample failures: ({", ".join(bad_build_ids[:max(len(bad_build_ids), 10)])})'

  success_str = f'{common.BOLDGREEN}Success{common.RESET}' if success else f'{common.BOLDRED}Non-success{common.RESET}'
  status_str = f'{success_str}: {get_builder_link(builder)} --> {problem_str}'

  return not success, status_str


def determine_maximum_covered_instance(
    all_builds: Builds, changes: List[git.Commit],
    checks: Tuple[staging_checks.StagingReCheck], enforce_success: bool = False,
    verbose: bool = False) -> Tuple[common.CipdInstance, List[str]]:
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
    enforce_success: If set, will enforce that builds are successful rather
      than just enforcing coverage.
    verbose: If set, more information is logged.
  Returns:
    - The most recent CIPD instance that had adequate coverage in staging.
    - A list of any (new) builders that have insufficient results.
  """
  builders = set()
  num_builds_by_builder = {}
  for re_check in checks:
    for builder in return_builders_for_regex(re_check.project, re_check.bucket,
                                             re_check.regex):
      builders.add(builder)
      num_builds_by_builder[builder] = re_check.num_builds

  recipe_by_builder = {}
  # Recipes used by sentinel builders.
  for builder in builders:
    recipe_by_builder[builder] = get_builder_recipe(builder)

  # `changes` is ordered newest to oldest.
  changes = sorted(changes, reverse=True)
  change_coverage_per_build = defaultdict(lambda: {})
  earliest_change = min(changes)

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
      of builds covering changes[i], or None if the builder should be
      disregarded (e.g. if it's a new builder with not enough runs yet).
    """
    # Get all build results since the oldest pending change.
    builds = all_builds.get_builds_after(builder, earliest_change)
    num_builds = num_builds_by_builder[builder]

    # If there are not enough builds for the builder, don't let that be a
    # blocker.
    if len(builds) < num_builds:
      if len(_bb_ls('-fields', 'id', builder, '-n',
                    str(num_builds))) < num_builds:
        print_if_verbose(
            f'<{num_builds} build results for {builder}, it must be new. Not enforcing coverage.'
        )
        return None

    print_if_verbose(
        f'Found {len(builds):3} builds for {builder} since {earliest_change.hash}.'
    )

    # change_coverage contains the number of builds that ran each change.
    change_coverage = [0] * len(changes)

    # We calculate change_coverage for a builder as follows:
    # Maintain a pointer to the current change (starts at the newest change).
    # Step through the builds, newest to oldest.
    # If the builder ran the current change, increment change_coverage for that change.
    # Otherwise, advance the change pointer until we reach a change that was covered by this buuld.
    change_pointer = 0
    build_pointer = 0
    # Step through builds newest to oldest.
    builds = sorted(builds, key=lambda build: build['createTime'], reverse=True)
    while build_pointer < len(builds):
      build = builds[build_pointer]
      cipd_version = build_to_cipd_version(build)
      # If there's no cipd_version we can't use this build result.
      if not cipd_version:
        build_pointer += 1
        continue

      # Stop looking once we have sufficient coverage to reduce runtime.
      if change_coverage[change_pointer] >= num_builds:
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
    # If we haven't processed all the changes (because we ran out of builds),
    # copy coverage to all the remaining (older) changes.
    for j in range(change_pointer + 1, len(changes)):
      change_coverage[j] = change_coverage[change_pointer]
    return change_coverage

  # Get change coverage for each builder. Multithread for performance.
  with concurrent.futures.ThreadPoolExecutor() as executor:
    for builder in builders:
      change_coverage_per_build[builder] = executor.submit(
          get_change_coverage, builder)

  # Collect results. Re-order so the oldest change is first.
  new_builders = []
  for builder in change_coverage_per_build:
    change_coverage_per_build[builder] = change_coverage_per_build[
        builder].result()
    if change_coverage_per_build[builder]:
      change_coverage_per_build[builder] = change_coverage_per_build[
          builder][::-1]
    else:
      new_builders.append(builder)
  changes = changes[::-1]

  last_covered_change = None
  affected_recipes = set()
  for i, change in enumerate(changes):
    # Less confusing for humans if we don't use a trivial change for release.
    if change.trivial:
      continue

    print_if_verbose(f'Considering commit {change.hash}')

    affected_recipes_by_this_change = get_affected_recipes(
        [change], list(set(recipe_by_builder.values())))
    affected_recipes.update(set(affected_recipes_by_this_change))
    print_if_verbose(
        f'Affected recipes: {",".join(affected_recipes_by_this_change)}')
    print_if_verbose(
        f'Affected recipes (cumulative): {",".join(affected_recipes)}')

    # Can't release a change that doesn't have an associated instance.
    # Still want to update affected_recipes, so do that before exiting.
    if change.get_cipd_instance() == git.MISSING_INSTANCE:
      print_if_verbose('Change has no associated CIPD instance, skipping...')
      continue
    # If there are multiple changes associated with a CIPD instance, we only
    # want to consider the last one to ensure that we properly compute
    # the list of relevant builders (relevancy is additive, and we still
    # compute relevancy for the changes we skip here -- see above).
    if i < len(changes) - 1 and change.get_cipd_instance() == changes[
        i + 1].get_cipd_instance():
      print_if_verbose(
          'Subsequent changes have the same associated CIPD instance'
          ", won't consider this change for release...")
      continue

    missing_coverage = False
    for builder in builders:
      # Make sure we have sufficient coverage for all relevant builders.
      if recipe_by_builder[builder] not in affected_recipes:
        continue
      # Don't block on builders with insufficient builds.
      if not change_coverage_per_build[builder]:
        continue
      if change_coverage_per_build[builder][i] < num_builds_by_builder[builder]:
        print_if_verbose(
            f'{change.hash} lacking coverage in {builder} '
            f'({change_coverage_per_build[builder][i]}/{num_builds_by_builder[builder]} builds).\n'
            f'  Builder: {get_builder_link(builder)}')
        missing_coverage = True
        break
    if missing_coverage:
      break
    print_if_verbose(f'Commit {change.hash} is covered.')
    if enforce_success:
      if check_staging_builders(all_builds, changes[:i + 1], checks,
                                ok_fewer=new_builders, log_messages=verbose):
        continue
      print_if_verbose('Everything looks good!')
    last_covered_change = change

  if last_covered_change:
    return last_covered_change.get_cipd_instance(), new_builders
  return None, new_builders
