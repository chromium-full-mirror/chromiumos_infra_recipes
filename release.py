#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release a CrOS infra recipe bundle to prod."""

import argparse
from functools import lru_cache
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import typing
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import urllib.parse

import tabulate

# [VPYTHON:BEGIN]
# wheel: <
#   name: "infra/python/wheels/tabulate-py3"
#   version: "version:0.8.10"
# >
# [VPYTHON:END]

RECIPES_DIR = os.path.dirname(os.path.realpath(__file__))
RECIPE_BUNDLE = os.path.join('infra', 'recipe_bundles',
                             'chromium.googlesource.com', 'chromiumos', 'infra',
                             'recipes')
RE_TRIVIAL_COMMIT = re.compile(r'Roll recipe.*\(trivial\)\.?$')

MIN_BRANCH_MILESTONE = 113

BOLDRED = '\033[1;31m'
BOLDGREEN = '\033[1;32m'
BOLDBLUE = '\033[1;34m'
RESET = '\033[0m'


# A tuple containing the project, builder and regex used to search.
class StagingReCheck(typing.NamedTuple):
  project: str
  bucket: str
  regex: str
  # exemptions can turn failures into successes.
  # The input is a dict parsed from the `bb ls` output, e.g.
  # {"id":"8782723488170713857","builder":{"project":"chromeos", ...
  # The output should be True if the failure can be ignored.
  exemptions: List[Callable[[Dict[str, Any]], bool]] = []


def orchestrator_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for orchestrator builds."""
  ignorable_summary_markdown_re = [
      re.compile(r'\d+ out of \d+ builds failed'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


def image_builder_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for image builds."""
  ignorable_summary_markdown_re = [
      re.compile(r'^failed unit tests for'),
      re.compile(r'^failed compilation for'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


def cq_cancelled_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for CQ builds cancelled by CV."""
  ignorable_cancellation_markdown = 'LUCI CV no longer needs this Tryjob'
  return build.get('cancellationMarkdown',
                   '') == ignorable_cancellation_markdown


def merge_conflict_exemption(build: Dict[str, Any]) -> bool:
  """Exemption function for CQ builds that hit merge conflicts."""
  ignorable_summary_markdown_re = [
      re.compile(r'^Merge conflict detected!'),
  ]
  for regex in ignorable_summary_markdown_re:
    if regex.search(build.get('summaryMarkdown', '')):
      return True
  return False


STAGING_CHECKS_RE = (StagingReCheck('chromeos', 'staging',
                                    r'staging-amd64-generic-postsubmit',
                                    [image_builder_exemption]),)
STAGING_CHECKS_RE = (
    StagingReCheck('chromeos', 'staging',
                   r'staging-release-R(?P<milestone>\d+)-\d+\.B-orchestrator'),
    StagingReCheck('chromeos', 'staging',
                   r'staging-octopus-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption]),
    StagingReCheck('chromeos', 'staging',
                   r'staging-zork-release-R(?P<milestone>\d+)-\d+\.B',
                   [image_builder_exemption]),
    # TODO(b/278066948): When lts staging runs are replicated, enable checking them.
    # StagingReCheck('chromeos', 'staging', 'staging-release-R\d+-\d+\.B-cq-orchestrator'),
    StagingReCheck('chromeos', 'staging', r'LegacyNoopSuccess'),
    StagingReCheck('chromeos', 'staging',
                   r'staging-amd64-generic-direct-tast-vm'),
    StagingReCheck('chromeos', 'staging', r'staging-amd64-generic-postsubmit',
                   [image_builder_exemption]),
    StagingReCheck('chromeos', 'staging', r'staging-Annealing'),
    StagingReCheck('chromeos', 'staging', r'staging-backfiller'),
    StagingReCheck('chromeos', 'staging', r'staging-chrome-pupr-generator'),
    StagingReCheck('chromeos', 'staging', r'staging-cq-orchestrator', [
        orchestrator_exemption, cq_cancelled_exemption, merge_conflict_exemption
    ]),
    StagingReCheck('chromeos', 'staging', r'staging-DutTracker'),
    StagingReCheck('chromeos', 'staging', r'staging-firmware-ti50-postsubmit'),
    StagingReCheck('chromeos', 'staging', r'staging-manifest-doctor'),
    StagingReCheck('chromeos', 'staging', r'staging-paygen'),
    StagingReCheck('chromeos', 'staging', r'staging-paygen-orchestrator'),
    StagingReCheck('chromeos', 'staging', r'staging-release-main-orchestrator'),
    StagingReCheck('chromeos', 'staging', r'staging-release-triggerer'),
    StagingReCheck('chromeos', 'staging', r'staging-RoboCrop'),
    StagingReCheck('chromeos', 'staging', r'staging_SourceCacheBuilder'),
    StagingReCheck('chromeos', 'staging', r'staging-StarDoctor'),
)

# CipdInstances are instance IDs, as found on the CIPD UI under "Instances".
# For example: "M4HmuQVGbx8YQVkM61c6LnCHVFgpJsSy1bI4DpBjSTwC"
CipdInstance = typing.NewType('CipdInstance', str)
# CipdRefs are named refs, as found on the CIPD UI under "Refs".
# For example: "prod" or "release_2022/09/23-12".
CipdRef = typing.NewType('CipdRef', str)
# CipdVersions can be either instance IDs or named refs.
# These are commonly accepted by the cipd CLI's `-version` flag.
CipdVersion = typing.Union[CipdInstance, CipdRef]
# GitHashes are the SHA of a Git commit (in the recipes repo).
# For example: "5d185ee5339976575a282971eef16f590405217f"
GitHash = typing.NewType('GitHash', str)


def main(argv: List[str]):
  options = parse_args(argv)
  setup()

  # Figure out which hashes/instances to use.
  git_prod = get_git_prod_hash()
  (cipd_target, git_target) = determine_cipd_and_git_targets(options.instanceid)

  # Prepare to update refs.
  pending_changes = get_pending_changes(git_prod, git_target)
  report_pending_changes(pending_changes, options.show_instances,
                         verbose=options.verbose)

  check_staging_builders(pending_changes,
                         ignore_failures=options.ignore_staging_failures)
  quit_early_if_no_pending_changes(pending_changes)
  if not options.force:
    prompt_about_setting_git_target(git_target)

  # Update refs.
  update_cipd_refs(cipd_target, dry_run=options.dry_run)

  # We did it!
  print_email_link(pending_changes)


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
    cmd = ['cipd', 'search', RECIPE_BUNDLE, '-tag', tag]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)

    for line in [line.strip() for line in p.stdout.split('\n')]:
      if line.startswith(RECIPE_BUNDLE):
        return line.split(':')[1]
    return '---------COULD_NOT_FIND_INSTANCE--------'

  def set_cipd_instance(self, instanceid: CipdInstance):
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
        f'{BOLDBLUE}{self.short_hash}', self.date,
        f'{BOLDGREEN}[{self.username}] ', f'{RESET}{self.message}'
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


def parse_args(args: List[str]) -> argparse.Namespace:
  """Interpret command-line args."""
  parser = argparse.ArgumentParser(
      'Release recipes by moving the "prod" ref forward.')
  parser.add_argument('-d', '--dry-run', action='store_true',
                      help='Dry run: Don\'t actually change any cipd refs.')
  parser.add_argument('-f', '--force', action='store_true',
                      help='Bypass the prompt.')
  parser.add_argument(
      '-i', '--instanceid', type=CipdInstance,
      help='Release up to the commit specified by the instanceid. '
      'Instanceids are found at:\n'
      'https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+/\n'
      'Click into an instance to see the commit attached to it.')
  parser.add_argument(
      '--show-instances', action='store_true',
      help='Show the CIPD instance IDs built from each commit. '
      'Intended to inform -i/--instance-id usage.')
  parser.add_argument('-s', '--ignore-staging-failures', action='store_true',
                      help='Release even if staging failures are present.')
  parser.add_argument(
      '-v', '--verbose', action='store_true',
      help='Print all pending changes, including trivial recipe rolls.')
  return parser.parse_args(args)


def setup():
  """Prepare for main logic."""
  git_remote_update()
  print_cipd_versions_url()


def git_remote_update():
  """Run `git remote update` in the recipes dir."""
  subprocess.run(['git', 'remote', 'update'], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, cwd=RECIPES_DIR, check=True)


def print_cipd_versions_url():
  """Tell the user where to get info about CIPD versions."""
  print('CIPD versions (instances and refs) can be found here:')
  print(
      'https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+/'
  )
  print()


def get_git_prod_hash() -> GitHash:
  """Get the git hash for the current prod ref."""
  return cipd_version_to_githash(CipdRef('prod'))


def cipd_version_to_githash(version: CipdVersion) -> GitHash:
  """Find the git hash for a recipes CIPD instance (whether named ref or ID).

  Sample `cipd describe` output:
  Package:       infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes
  Instance ID:   dv0onkHQ71tjY2cvQiePm-ve1tCfbHfvi40xJWs5EbAC
  Registered by: user:infra-internal-recipe-bundler@chops-service-accounts.iam.gserviceaccount.com
  Registered at: 2022-09-23 13:11:22.569365 -0600 MDT
  Refs:
    prod
    release_2022/09/23-12
  Tags:
    git_revision:1114d30c71229c5cd470df15f863e9ddcfff6fb5
  """
  cmd = ['cipd', 'describe', '-version', version, RECIPE_BUNDLE]
  p = subprocess.run(cmd, text=True, capture_output=True, check=True)
  lines = p.stdout.split('\n')
  git_rev_lines = [line for line in lines if 'git_revision' in line]
  assert len(git_rev_lines) >= 1, lines
  git_rev_line = git_rev_lines[0]
  assert git_rev_line.count(':') == 1, git_rev_line
  githash = git_rev_line.strip().split(':')[1]
  assert all(c in string.hexdigits for c in githash), githash
  return GitHash(githash)


def determine_cipd_and_git_targets(
    instanceid: Optional[CipdInstance] = None) -> Tuple[CipdInstance, GitHash]:
  """Find the target CIPD instance (if not provided) and Git hash."""
  if instanceid:
    git_target = cipd_version_to_githash(instanceid)
    cipd_target = instanceid
  else:
    git_target = cipd_version_to_githash(CipdInstance('refs/heads/main'))
    cipd_target = cipd_ref_to_instance_id(CipdRef(f'git_revision:{git_target}'))
  return (cipd_target, git_target)


def cipd_ref_to_instance_id(ref: CipdRef) -> CipdInstance:
  """Find the instanceid associated with a recipes CIPD ref."""
  p = subprocess.run(['cipd', 'resolve', '-version', ref, RECIPE_BUNDLE],
                     capture_output=True, text=True, check=True)
  stdout = [line.strip() for line in p.stdout.split('\n') if line]
  instance_id = stdout[-1].split(':')[-1]
  assert len(instance_id.split()) == 1, instance_id
  return CipdInstance(instance_id)


def build_to_cipd_version(build: Dict[str, Any]) -> Optional[CipdVersion]:
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
    if spec['package'] == RECIPE_BUNDLE:
      recipes_version = spec['version']

  if not recipes_version:
    raise ValueError(
        f"resolved recipes version not found for build {build['builder']['builder']}"
    )

  return recipes_version


def get_pending_changes(from_hash: GitHash, to_hash: GitHash) -> List[Commit]:
  """Find all changes that will be released.

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
  p = subprocess.run(cmd, capture_output=True, text=True, cwd=RECIPES_DIR,
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


def report_pending_changes(pending_changes: List[Commit], show_instances: bool,
                           verbose: bool):
  """Pretty-print info about all the pending changes."""
  if verbose:
    print(' - Verbose specified, printing all changes')
  change_strs = []
  for pending_change in pending_changes:
    if pending_change.trivial and not verbose:
      continue
    change_strs.append(pending_change.color_strs(show_instances=show_instances))

  print(tabulate.tabulate(change_strs, headers=[], tablefmt='plain'))


@lru_cache(maxsize=None)
def _get_affected_recipes(newest_change: Commit, oldest_change: Commit,
                          recipes: str) -> List[str]:
  """Inner (cachable) function for get_affected_recipes."""
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


def get_affected_recipes(newest_change: Commit, oldest_change: Commit,
                         recipes: List[str]) -> List[str]:
  """Get the list of recipes affected by the given commits.

  Args:
    recipes: List of recipes used by the staging builders. Required arg for
      `./recipes.py analyze`.
  """
  return _get_affected_recipes(newest_change, oldest_change,
                               ','.join(sorted(recipes)))


@lru_cache(maxsize=None)
def _get_builder_recipe(builder: str):
  """Get the recipe used by the given builder."""
  cmd = ['led', 'get-builder', builder]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)
  builder_data = json.loads(p.stdout)
  return builder_data['buildbucket']['bbagent_args']['build']['input'][
      'properties']['recipe']


def check_staging_builders(changes: List[Commit],
                           ignore_failures: bool = False):
  """Check for failures in staging builders. Quit early if any problems."""
  print('=== Check staging status ===')
  print('Determining relevancy of each staging builder...')
  builders = []
  for re_check in STAGING_CHECKS_RE:
    builders.extend(
        return_builders_for_regex(re_check.project, re_check.bucket,
                                  re_check.regex))

  builder_recipes = {}
  # Recipes used by sentinel builders.
  for builder in builders:
    builder_recipes[builder] = _get_builder_recipe(builder)

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
  for re_check in STAGING_CHECKS_RE:
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


@lru_cache(maxsize=None)
def is_older_than(maybe_older_hash: str, commit_hash: str) -> bool:
  cmd = ['git', 'merge-base', '--is-ancestor', maybe_older_hash, commit_hash]
  p = subprocess.run(cmd, capture_output=True, text=True)  #pylint: disable=subprocess-run-check
  if p.returncode == 0:
    return True
  if p.returncode == 1:
    return False
  raise Exception(f'error calling `{" ".join(cmd)}`: {p.stderr}')


def check_recent_build_statuses(
    builder: str,
    exemptions: List[Callable[[Dict[str, Any]], bool]],
    pending_changes: List[Commit],
    diff_fn: Callable[[Commit], List[str]],
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
      githashes.append(cipd_version_to_githash(cipd_version))

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
    if is_older_than(change.hash, most_recent_githash):
      break

    if not change.trivial:
      non_trivial_changes_since_most_recent_build.append(change)

  num_non_trivial_changes_since_most_recent_build = len(
      non_trivial_changes_since_most_recent_build)

  success = set(found_statuses).issubset({'SUCCESS', 'OK_FAILURE'})
  success_str = f'{BOLDGREEN}Success{RESET}' if success else f'{BOLDRED}Non-success{RESET}'
  status_str = f'{success_str}: {get_builder_link(builder)} --> {", ".join(sorted(list(found_statuses)))}'

  relevant_changes = []
  builder_recipe = _get_builder_recipe(builder)
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
          f'{BOLDBLUE}{non_trivial_pending_changes[num_non_trivial_changes_since_most_recent_build].short_hash}{RESET}'
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


def quit_early_if_no_pending_changes(pending_changes: List[Commit]):
  """If there are no pending changes, exit gracefully."""
  if not pending_changes:
    print('No changes pending. Exiting early.')
    sys.exit(0)


def prompt_about_setting_git_target(git_target: GitHash):
  """Ask the user whether it's OK to change the git target. If not, exit."""
  if input(f'Set prod to git @ {git_target}? (y/N): ').upper() != 'Y':
    sys.exit(0)


def update_cipd_refs(cipd_target: CipdInstance, dry_run: bool = False):
  """Set the prod ref and timestamped ref to the given cipd instance."""
  prod_ref = CipdRef('prod')
  timestamped_ref = CipdRef(f'release_{get_timestamp("%Y/%m/%d-%H")}')
  for ref in (prod_ref, timestamped_ref):
    cmd = [
        'cipd', 'set-ref', RECIPE_BUNDLE, f'-version={cipd_target}',
        f'-ref={ref}'
    ]
    if dry_run:
      print('Not actually running the following command:')
      print('\t ', ' '.join(cmd))
    else:
      subprocess.run(cmd, check=True)


def get_timestamp(fmt: str = ''):
  """Get a current timestamp in California time.

  Use Bash's `date` because Python standard lib is shockingly bad at timezones
  prior to Py3.9.
  """
  env = {'TZ': 'America/Los_Angeles'}
  cmd = ['date']
  if fmt:
    cmd.append(f'+{fmt}')
  p = subprocess.run(cmd, capture_output=True, text=True, env=env, check=True)
  return p.stdout.strip()


def print_email_link(pending_changes: List[Commit]):
  """Show the user an email link to announce the new change."""
  print()
  print('Please click this link and send an email to chromeos-infra-releases!')
  print()
  print(get_email_link(pending_changes))


def get_email_link(pending_changes: List[Commit]) -> str:
  """Create an email link to announce the new change."""
  email_subject = f'Recipes Release - {get_timestamp()}'
  email_message = '\n'.join([
      'We\'ve deployed Recipes to prod!',
      '',
      'Here is a summary of the changes:',
      '',
      tabulate.tabulate([
          c.plain_strs(with_bullet=True)
          for c in pending_changes
          if not c.trivial
      ], headers=[], tablefmt='plain'),
  ])
  url_params = urllib.parse.urlencode({
      'view': 'cm',
      'fs': 1,
      'bcc': 'chromeos-infra-releases@google.com',
      'to': 'chromeos-continuous-integration-team@google.com',
      'su': email_subject,
      'body': email_message,
  })
  url = f'https://mail.google.com/mail?{url_params}'
  return url


def get_builder_link(builder: str) -> str:
  if not builder.startswith('chromeos/staging/'):
    raise ValueError(
        f"expected builder to start with 'chromeos/staging', got {builder}")

  builder_name = builder.replace('chromeos/staging/', '', 1)
  return f'https://ci.chromium.org/p/chromeos/builders/staging/{builder_name}'


if __name__ == '__main__':
  main(sys.argv[1:])
