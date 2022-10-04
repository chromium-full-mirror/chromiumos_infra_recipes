#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release a CrOS infra recipe bundle to prod."""

import argparse
import json
import os
import re
import string
import subprocess
import sys
import typing
from typing import List
from typing import Optional
from typing import Tuple
import urllib.parse

RECIPES_DIR = os.path.dirname(os.path.realpath(__file__))
RECIPE_BUNDLE = os.path.join('infra', 'recipe_bundles',
                             'chromium.googlesource.com', 'chromiumos', 'infra',
                             'recipes')
RE_TRIVIAL_COMMIT = re.compile(r'Roll recipe.*\(trivial\)\.?$')
STAGING_CHECKS = (
    "LegacyNoopSuccess",
    "staging-amd64-generic-direct-tast-vm",
    "staging-amd64-generic-postsubmit",
    "staging-Annealing",
    "staging-backfiller",
    "staging-chrome-pupr-generator",
    "staging-DutTracker",
    "staging-firmware-ti50-postsubmit",
    "staging-manifest-doctor",
    "staging-release-main-orchestrator",
    "staging-RoboCrop",
    "staging-StarDoctor",
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
  pending_changes = get_pending_changes(git_prod, git_target,
                                        verbose=options.verbose)
  report_pending_changes(pending_changes)
  check_staging_builders(options.ignore_staging_failures)
  quit_early_if_no_pending_changes(pending_changes)
  if not options.force:
    prompt_about_setting_git_target(git_target)

  # Update refs.
  update_cipd_refs(cipd_target, dry_run=options.dry_run)

  # We did it!
  print_email_link(pending_changes)


class Commit:

  def __init__(self, git_hash, username, message):
    self.hash = git_hash
    self.username = username
    self.message = message

  def color_str(self) -> str:
    """Return a colorified string for printing to stdout."""
    BOLDBLUE = '\033[1;34m'
    BOLDGREEN = '\033[1;32m'
    RESET = '\033[0m'
    return f'{BOLDBLUE}{self.hash} {BOLDGREEN}[{self.username}] {RESET}{self.message}'

  def plain_str(self, with_bullet: bool = False) -> str:
    """Return a colorless string for printing to email."""
    prefix = '* ' if with_bullet else ''
    return f'{prefix}{self.hash} [{self.username}] {self.message}'


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
      'https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+\n'
      'Click into an instance to see the commit attached to it.')
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


def determine_cipd_and_git_targets(instanceid: Optional[CipdInstance] = None
                                  ) -> Tuple[CipdInstance, GitHash]:
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


def get_pending_changes(from_hash: GitHash, to_hash: GitHash,
                        verbose: bool = False) -> List[Commit]:
  """Find all changes that will be released.

  from_hash: The git hash immediately preceding the first in the changelist.
  to_hash: The final git hash of the changelist.
  verbose: If False, exclude trivial recipe rolls.
  """
  print('=== Checking for pending changes ===')
  print('Here are the changes from the provided (or default main) environment:')
  if verbose:
    print(' - Verbose specified, printing all changes')
  fmt = '%h %al %s'  # %h=commit, %al=user, %s=summary
  cmd = [
      'git', 'log', '--graph', f'--pretty=format:{fmt}',
      f'{from_hash}..{to_hash}'
  ]
  p = subprocess.run(cmd, capture_output=True, text=True, cwd=RECIPES_DIR,
                     check=True)
  if p.stderr:
    print(f'Error running cmd: {cmd}')
    print(p.stderr)
    sys.exit(1)
  lines = [line.strip().lstrip('* ') for line in p.stdout.split('\n')]
  changes = []
  for line in lines:
    if not line:
      continue
    commit_hash, commit_user, commit_message = line.split(' ', 2)
    if RE_TRIVIAL_COMMIT.match(commit_message) and not verbose:
      continue
    changes.append(Commit(commit_hash, commit_user, commit_message))
  return changes


def report_pending_changes(pending_changes: List[Commit]):
  """Pretty-print info about all the pending changes."""
  for pending_change in pending_changes:
    print(f'* {pending_change.color_str()}')
  print()


def check_staging_builders(ignore_failures: bool = False):
  """Check for failures in staging builders. Quit early if any problems."""
  print('=== Check staging status ===')
  baddies = []
  print('Looking for 5 consecutive successes in staging.')
  for name in STAGING_CHECKS:
    builder = f'chromeos/staging/{name}'
    if has_builder_had_non_success(builder):
      baddies.append(name)
  if baddies:
    if ignore_failures:
      print('Ignoring failures, as requested.')
    else:
      print('Please address the failures in the above builders.')
      print('When you\'re certain staging is OK, you may use -s to continue.')
      sys.exit(1)
  print()


def has_builder_had_non_success(builder: str) -> bool:
  """Check whether a single builder has had any recent non-successes."""
  print(f'Checking the status of: {builder} --> ', end='')
  cmd = ['bb', 'ls', '-n', '5', '-json', builder]
  p = subprocess.run(cmd, capture_output=True, text=True, check=True)
  unique_statuses = []
  for line in p.stdout.split('\n'):
    if not line:
      continue
    status = json.loads(line)['status']
    if status in ('STARTED', 'SCHEDULED'):
      continue
    if status not in unique_statuses:
      unique_statuses.append(status)
  print(', '.join(unique_statuses))
  return unique_statuses != ['SUCCESS']


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
      '\n'.join(
          change.plain_str(with_bullet=True) for change in pending_changes),
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


if __name__ == '__main__':
  main(sys.argv[1:])
