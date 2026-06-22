#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release a CrOS infra recipe bundle to prod."""

import argparse
import logging
import os
import pathlib
import subprocess
import sys
import typing
from typing import List
from typing import Tuple

from google.protobuf import json_format
import tabulate

import bb
import cipd
import common
import git
import gmail
from protos.recipes_autoreleaser import ReleaseResult  #pylint: disable=no-name-in-module
import staging_checks

logger = logging.getLogger(__name__)


RECIPES_DIR = os.path.dirname(os.path.realpath(__file__))


class RecipeReleaseConfig(typing.NamedTuple):
  """A tuple containing the project, builder and regex used to search."""
  name: str
  staging_checks: Tuple[staging_checks.StagingReCheck]
  prod_cipd_label: common.CipdRef
  longname: str

# These variables describe config for the different recipes releases.
# We have `infra`, which is most everything, and `release`, which is used
# only by release builders.

INFRA_BUNDLE = RecipeReleaseConfig(
    'infra', staging_checks.INFRA_BUNDLE_STAGING_CHECKS_RE,
    common.CipdRef('prod'), 'ChromeOS Infrastructure')
RELEASE_BUNDLE = RecipeReleaseConfig(
    'release', staging_checks.RELEASE_BUNDLE_STAGING_CHECKS_RE,
    common.CipdRef('release-prod'), 'ChromeOS Release')


class RecipeRelease:

  def __init__(self, config: RecipeReleaseConfig):
    self.name = config.name
    self.staging_checks = config.staging_checks
    self._prod_cipd_ref = config.prod_cipd_label
    self._longname = config.longname

  def prompt_about_setting_git_target(self, git_target: common.GitHash):
    """Ask the user whether it's OK to change the git target. If not, exit."""
    if input(f'Set {self._prod_cipd_ref} to git @ {git_target}? (y/N): ').upper(
    ) != 'Y':
      sys.exit(common.RET_CODE_OK_NO_RELEASE)

  def update_cipd_refs(self, cipd_target: common.CipdInstance,
                       dry_run: bool = False):
    """Set the prod ref and timestamped ref to the given cipd instance."""
    prod_ref = common.CipdRef(self._prod_cipd_ref)

    timestamped_ref = common.CipdRef(
        f'release_{self.name}_{common.get_timestamp("%Y/%m/%d-%H")}')
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

  def do_release_flow(self, options: argparse.Namespace) -> ReleaseResult:
    if options.send_email:
      # If send_email is set, check early to see if we are logged into luci-auth
      # with the appropriate scopes. This way, the user will find out if they
      # aren't logged in early, instead of after the entire script is run.
      # get_token_from_luci_auth returns a token, but we don't actually use it,
      # we just want to see if it fails.
      gmail.get_token_from_luci_auth()

    # Figure out which hashes/instances to use.
    git_prod = cipd.cipd_version_to_githash(self._prod_cipd_ref)
    (cipd_target,
     git_target) = cipd.determine_cipd_and_git_targets(options.instanceid)

    # Prepare to update refs.
    pending_changes = git.get_pending_changes(RECIPES_DIR, git_prod, git_target)
    report_pending_changes(pending_changes, options.show_instances,
                           show_all=options.show_all)

    quit_early_if_no_pending_changes(pending_changes)

    logger.info('=== Fetching build results, this may take a minute... ===')
    all_builds = bb.Builds()
    all_builds.initialize(self.staging_checks, pending_changes,
                          verbose=options.verbose)

    new_builders = []
    if options.max_covered or options.max_releasable:
      option = 'releasable' if options.max_releasable else 'covered'
      logger.info('=== Determining maximum %s version ===', option)
      selected_instance, new_builders = bb.determine_maximum_covered_instance(
          all_builds, pending_changes, self.staging_checks,
          verbose=options.verbose, enforce_success=options.max_releasable)
      if not selected_instance:
        logger.error(
            'Could not find a %s version. Please rerun without --max-%s.',
            option,
            option,
        )
        sys.exit(common.RET_CODE_NO_RELEASABLE if options
                 .max_releasable else common.RET_CODE_NO_COVERED)
      print(f'Picked {selected_instance} for release.')
      options.instanceid = selected_instance
      # Recalculate pending changes.
      (cipd_target,
       git_target) = cipd.determine_cipd_and_git_targets(options.instanceid)
      pending_changes = git.get_pending_changes(RECIPES_DIR, git_prod,
                                                git_target)
      report_pending_changes(pending_changes, options.show_instances,
                             show_all=options.show_all)

    quit_early_if_no_pending_changes(pending_changes)

    # Unless we explicitly care about trivial changes, drop all the changes
    # that have landed since the last nontrivial change. They'll still get
    # released but shouldn't influence our staging checks.
    if not options.show_all:
      pending_changes = git.trim_trivial_suffix(pending_changes)
    logger.info('=== Check staging status ===')
    bad_builders = bb.check_staging_builders(all_builds, pending_changes,
                                             self.staging_checks, new_builders,
                                             log_messages=True)
    if bad_builders:
      if options.ignore_staging_failures:
        print('Ignoring failures, as requested.')
      else:
        logger.error('Please address the failures in the above builders.')
        logger.error(
            "When you're certain staging is OK, you may use -s to continue.")
        sys.exit(common.RET_CODE_OK_STAGING_FAILURES)
    else:
      print('Everything looks good!')
    print()

    # In dry run mode, don't bother asking for confirmation (no actions will be
    # taken anyway).
    if not options.yes and not options.dry_run:
      self.prompt_about_setting_git_target(git_target)

    # Update refs.
    self.update_cipd_refs(cipd_target, dry_run=options.dry_run)

    # Send the email announcement or produce a link for a human to send it.
    gm_client = gmail.GmailAnnouncer(
        # Changes should appear newest to oldest in the annoucement.
        sorted(pending_changes, reverse=True),
        bundle_longname=self._longname,
        recipients=options.recipients,
        bccs=options.bccs,
        dry_run=options.dry_run,
        quota_project=options.gmail_api_quota_project,
        bbid=options.bbid,
    )
    if options.send_email:
      gm_client.send_email()
      print(f'\nSent an announcement email to {",".join(options.recipients)}!')
    else:
      print(
          f'\nPlease click this link and send an email to {",".join(options.recipients)}!\n'
          + gm_client.get_email_link())

    return ReleaseResult(
        announcement_email=ReleaseResult.AnnouncementEmail(
            subject=gm_client.get_subject(),
            body=gm_client.body,
        ),
        released_commits=[
            # Return non-trivial changes sorted newest to oldest.
            c.to_proto()
            for c in sorted(pending_changes, reverse=True)
            if not c.trivial
        ],
    )


def setup_logging(verbose: bool) -> None:
  """Setup the logging module."""
  root_logger = logging.getLogger()
  root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)
  formatter = logging.Formatter(
      fmt="%(asctime)s: %(levelname)s: %(message)s",
      datefmt="%H:%M:%S",
  )
  handler = logging.StreamHandler()
  handler.setFormatter(formatter)
  root_logger.addHandler(handler)


def main(argv: List[str]):
  options = parse_args(argv)
  setup_logging(options.verbose)

  try:
    setup()

    logger.info('=== Releasing recipes bundle "%s" ===', options.bundle)
    bundle_config = {
        'infra': INFRA_BUNDLE,
        'release': RELEASE_BUNDLE,
    }[options.bundle]

    release = RecipeRelease(bundle_config)
    result = release.do_release_flow(options)
    if options.result_out:
      options.result_out.write_text(json_format.MessageToJson(result))
  except Exception:  #pylint: disable=broad-except
    logger.exception('Unknown failure')
    sys.exit(common.RET_CODE_INTERNAL_ERROR)
  sys.exit(common.RET_CODE_SUCCESS)


def parse_args(args: List[str]) -> argparse.Namespace:
  """Interpret command-line args."""
  parser = argparse.ArgumentParser(
      'Release recipes by moving the "prod" ref forward.')
  parser.add_argument('-n', '--dry-run', action='store_true',
                      help="Dry run: Don't actually change any cipd refs.")
  parser.add_argument(
      '-y', '--yes', action='store_true',
      help='Answer yes to prompts, e.g. whether to update the CIPD ref after '
      'checking staging results.')
  parser.add_argument(
      '--show-instances', action='store_true',
      help='Show the CIPD instance IDs built from each commit. '
      'Intended to inform -i/--instance-id usage.')
  parser.add_argument('-s', '--ignore-staging-failures', action='store_true',
                      help='Release even if staging failures are present.')
  parser.add_argument(
      '--bundle', choices=['infra', 'release'], default='infra',
      help='Bundles available for a prod push. `release` is release builders,'
      '`infra` is everything else (not including CTP). (default: %(default)s)')
  parser.add_argument(
      '--show-all', action='store_true',
      help='Show all pending changes, including trivial recipe rolls.')
  parser.add_argument('-v', '--verbose', action='store_true',
                      help='Increase level of logging.')
  parser.add_argument(
      '--result-out',
      type=pathlib.Path,
      required=False,
      metavar='PATH',
      help='Path to write a recipes.chromeos.recipes_autoreleaser.'
      'ReleaseResult jsonproto to. This is used so the release script can '
      'commuicate results in a structured format to other programs calling it; '
      'in general humans should not need to set this arg, as the same info '
      'is displayed on stdout/err. Note that this may not be written in some '
      'error cases.',
  )

  mode_group = parser.add_mutually_exclusive_group()
  mode_group.add_argument(
      '-i', '--instanceid', type=common.CipdInstance,
      help='Release up to the commit specified by the instanceid. '
      'Instanceids are found at:\n'
      f'go/cipd/{cipd.PACKAGE_NAME}\n'
      'Click into an instance to see the commit attached to it.\n'
      "If the instance starts with a '-', you'll need to pass it in with"
      '`-i=$instance` instead of `-i $instance`.')
  mode_group.add_argument(
      '--max-covered', action='store_true',
      help='Find the maximum instance that has been adequately covered in staging.'
  )
  mode_group.add_argument(
      '--max-releasable', action='store_true',
      help='Find the maximum instance that has sufficient successful results in staging.'
      'Currently in development, use at your own risk.')

  email_group = parser.add_argument_group(
      'email',
      description='On success, the script will print a link for the caller to '
      'send an email announcing the release.',
  )
  email_group.add_argument(
      '--send-email',
      action='store_true',
      help='Send the email via the Gmail API instead of just printing a link '
      'for the caller to send it. Authenication is done by calling `luci-auth '
      'token`, so the caller must be logged into `luci-auth` with the required '
      'scopes. Login command: `luci-auth login -scopes '
      f'{" ".join(gmail.REQUIRED_SCOPES)}`',
  )
  email_group.add_argument(
      '--recipients',
      type=str,
      nargs='+',
      metavar='EMAIL',
      default=['chromeos-continuous-integration-team@google.com'],
      help='Email addresses to send the announcement to.',
  )
  email_group.add_argument(
      '--bccs',
      type=str,
      nargs='*',
      metavar='EMAIL',
      default=['chromeos-infra-releases@google.com'],
      help='Email addresses to bcc on the announcement. May be empty.',
  )
  email_group.add_argument(
      '--gmail-api-quota-project',
      type=str,
      default='chromeos-bot',
      help='Cloud project to use with the Gmail API. Only used if --send-email '
      'is set.',
  )
  email_group.add_argument(
      '--bbid',
      type=str,
      help='BBID of the invoking builder, which will be included in '
      'the announcement email. Not for use by humans.',
  )

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
  print(f'https://chrome-infra-packages.appspot.com/p/{cipd.PACKAGE_NAME}')
  print()


def report_pending_changes(pending_changes: List[git.Commit],
                           show_instances: bool, show_all: bool):
  """Pretty-print info about all the pending changes."""
  logger.info('=== Displaying pending changes ===')
  print('Here are the changes from the provided (or default main) environment:')
  if show_all:
    print(' - --show-all specified, printing all changes')
  change_strs = []
  for pending_change in pending_changes:
    if pending_change.trivial and not show_all:
      continue
    change_strs.append(pending_change.color_strs(show_instances=show_instances))

  print(tabulate.tabulate(change_strs, headers=[], tablefmt='plain'))


def quit_early_if_no_pending_changes(pending_changes: List[git.Commit]):
  """If there are no pending changes, exit gracefully."""
  if not pending_changes:
    print('No changes pending. Exiting early.')
    sys.exit(common.RET_CODE_OK_NO_CHANGES)


if __name__ == '__main__':
  main(sys.argv[1:])
