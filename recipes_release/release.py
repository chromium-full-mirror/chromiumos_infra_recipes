#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release a CrOS infra recipe bundle to prod."""

import argparse
import os
import subprocess
import sys
from typing import List
import urllib.parse

import tabulate

import bb
import cipd
import common
import git

# [VPYTHON:BEGIN]
# wheel: <
#   name: "infra/python/wheels/tabulate-py3"
#   version: "version:0.8.10"
# >
# [VPYTHON:END]

RECIPES_DIR = os.path.dirname(os.path.realpath(__file__))


def main(argv: List[str]):
  options = parse_args(argv)
  setup()

  # Figure out which hashes/instances to use.
  git_prod = cipd.get_git_prod_hash()
  (cipd_target,
   git_target) = cipd.determine_cipd_and_git_targets(options.instanceid)

  # Prepare to update refs.
  pending_changes = git.get_pending_changes(RECIPES_DIR, git_prod, git_target)
  report_pending_changes(pending_changes, options.show_instances,
                         verbose=options.verbose)

  bb.check_staging_builders(pending_changes,
                            ignore_failures=options.ignore_staging_failures)
  quit_early_if_no_pending_changes(pending_changes)
  if not options.force:
    prompt_about_setting_git_target(git_target)

  # Update refs.
  update_cipd_refs(cipd_target, dry_run=options.dry_run)

  # We did it!
  print_email_link(pending_changes)


def parse_args(args: List[str]) -> argparse.Namespace:
  """Interpret command-line args."""
  parser = argparse.ArgumentParser(
      'Release recipes by moving the "prod" ref forward.')
  parser.add_argument('-d', '--dry-run', action='store_true',
                      help='Dry run: Don\'t actually change any cipd refs.')
  parser.add_argument('-f', '--force', action='store_true',
                      help='Bypass the prompt.')
  parser.add_argument(
      '-i', '--instanceid', type=common.CipdInstance,
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


def report_pending_changes(pending_changes: List[git.Commit],
                           show_instances: bool, verbose: bool):
  """Pretty-print info about all the pending changes."""
  if verbose:
    print(' - Verbose specified, printing all changes')
  change_strs = []
  for pending_change in pending_changes:
    if pending_change.trivial and not verbose:
      continue
    change_strs.append(pending_change.color_strs(show_instances=show_instances))

  print(tabulate.tabulate(change_strs, headers=[], tablefmt='plain'))


def quit_early_if_no_pending_changes(pending_changes: List[git.Commit]):
  """If there are no pending changes, exit gracefully."""
  if not pending_changes:
    print('No changes pending. Exiting early.')
    sys.exit(0)


def prompt_about_setting_git_target(git_target: common.GitHash):
  """Ask the user whether it's OK to change the git target. If not, exit."""
  if input(f'Set prod to git @ {git_target}? (y/N): ').upper() != 'Y':
    sys.exit(0)


def update_cipd_refs(cipd_target: common.CipdInstance, dry_run: bool = False):
  """Set the prod ref and timestamped ref to the given cipd instance."""
  prod_ref = common.CipdRef('prod')
  timestamped_ref = common.CipdRef(
      f'release_{common.get_timestamp("%Y/%m/%d-%H")}')
  for ref in (prod_ref, timestamped_ref):
    cmd = [
        'cipd', 'set-ref', common.RECIPE_BUNDLE, f'-version={cipd_target}',
        f'-ref={ref}'
    ]
    if dry_run:
      print('Not actually running the following command:')
      print('\t ', ' '.join(cmd))
    else:
      subprocess.run(cmd, check=True)


def print_email_link(pending_changes: List[git.Commit]):
  """Show the user an email link to announce the new change."""
  print()
  print('Please click this link and send an email to chromeos-infra-releases!')
  print()
  print(get_email_link(pending_changes))


def get_email_link(pending_changes: List[git.Commit]) -> str:
  """Create an email link to announce the new change."""
  email_subject = f'Recipes Release - {common.get_timestamp()}'
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


if __name__ == '__main__':
  main(sys.argv[1:])
