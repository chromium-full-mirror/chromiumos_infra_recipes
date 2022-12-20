# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for managing release config."""

import datetime
import re

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.common import ReleaseBuilder, ReleaseBuilders
from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import Email

CONFIG = "release/release_builders.textpb"
STABILIZE_CONFIG = "release/stabilize_builders.textpb"
CHROMITE_ANDROID = "lib/constants.py"

TEST_DATA = ReleaseBuilders(builders=[
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='main', number=-1),
        build_schedule="0 1 * * *"),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R01-00001.B',
                                           number=1)),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R02-00002.B',
                                           number=2)),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R03-00003.B',
                                           number=3)),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R40-00040.B',
                                           number=40),
        expiration_date=ReleaseBuilder.Date(value='2100-01-01')),
])

RELEASE_BRANCH_REGEX = r'release-R(\d+)-\d+.B'


class CrosReleaseConfigApi(recipe_api.RecipeApi):
  LEGACY_CONFIG_PROJECT = "chromiumos/chromite"
  CONFIG_PROJECT = "chromeos/infra/config"

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._reviewers = properties.reviewers
    self._ccs = properties.ccs
    self._auto_submit = properties.auto_submit
    self._keep_n_milestones = properties.keep_n_milestones

  def _extract_milestone(self, release_branch):
    res = re.search(RELEASE_BRANCH_REGEX, release_branch)
    if res:
      return int(res.group(1))
    return None

  def _get_emails(self, people):
    return [k.email for k in people]

  def _get_builder_expiration_date(self, builder):
    """Get the expiration date for the builder.

    Returns none if the expiration date is not set or is malformatted.

    Args:
    builder (ReleaseBuilder): builder in question
    """
    try:
      return datetime.datetime.strptime(builder.expiration_date.value,
                                        "%Y-%m-%d")
    except ValueError:
      return None

  def _prune_builders(self, builders):
    """ Prune the list of builders.

    Prunes down to keep_n_milestones builders for release branches.
    ToT, LTS, or other builders are not counted.

    Args:
    builders (ReleaseBuilders): existing release builders.
    """
    if not self._keep_n_milestones:
      return builders

    to_keep = []
    true_release_builders = []

    for builder in builders.builders:
      pinned_by_date = False
      # Could potentially use the expiration dates in proto config as a source
      # of truth for the equivalent builder configs in legacy, and remove the
      # need for '# BOT-TAG:NO_PRUNE`.
      expiration_date = self._get_builder_expiration_date(builder)
      if expiration_date:
        pinned_by_date = expiration_date > datetime.datetime.now()
      if re.match(RELEASE_BRANCH_REGEX,
                  builder.milestone.branch_name) and not pinned_by_date:
        true_release_builders.append(builder)
      else:
        to_keep.append(builder)

    to_keep.extend(
        sorted(true_release_builders, key=lambda k: k.milestone.number,
               reverse=True)[:self._keep_n_milestones])
    return ReleaseBuilders(builders=to_keep)

  def _create_change(self, project, project_path, commit_message):
    with self.m.step.nest(
        'commit in {}'.format(project)), self.m.context(cwd=project_path):
      self.m.git.add([project_path])
      self.m.git.commit(commit_message)
    if self.m.buildbucket.build.created_by:
      parts = self.m.buildbucket.build.created_by.split(':')
      if len(parts) == 2 and parts[1].find('@') > 0:
        if not any(r.email == parts[1] for r in self._reviewers):
          self._reviewers.append(Email(email=parts[1]))
    change = self.m.gerrit.create_change(
        project_path, reviewers=self._get_emails(self._reviewers),
        ccs=self._get_emails(self._ccs))
    if self._auto_submit:
      self.m.gerrit.set_change_labels(change, {
          self.m.gerrit.Label.BOT_COMMIT: 1,
          self.m.gerrit.Label.COMMIT_QUEUE: 2,
      })

  def update_config(self, branch):
    """Creates CLs updating config file to include new release branch.

    While Rubik is being turned-up, this endpoint modifies both the legacy
    config in chromite as well as the Rubik starlark config in infra/config.

    Args:
    branch (str): Release or stabilize branch, e.g. "release-R89-13729.B" or
      "stabilize-15129.B".

    """
    milestone = None
    with self.m.step.nest('validate branch'):
      if not branch.startswith('release-') and not branch.startswith(
          'stabilize-'):
        raise StepFailure(
            "{} is not a release or stabilize branch".format(branch))

      is_release_branch = branch.startswith('release-')
      if is_release_branch:
        with self.m.step.nest('validate release branch'):
          milestone = self._extract_milestone(branch)
          if not milestone:
            raise StepFailure("bad release branch")

    with self.m.step.nest('validate CL settings'):
      if not self._reviewers and not self._auto_submit:
        raise StepFailure("no reviewers specified and auto submit is false")

    workpath = self.m.cros_source.workspace_path
    projects = [self.LEGACY_CONFIG_PROJECT, self.CONFIG_PROJECT]
    project_path = {}
    with self.m.step.nest('get project info'):
      with self.m.context(cwd=workpath):
        project_infos = self.m.repo.project_infos(projects=projects)
        for project in project_infos:
          project_path[project.name] = workpath.join(project.path)

    extra_text = ''
    with self.m.step.nest('update config'):
      config_path = project_path[self.CONFIG_PROJECT]
      with self.m.context(cwd=config_path):
        config_file = CONFIG if is_release_branch else STABILIZE_CONFIG
        file_path = config_path.join(config_file)

        release_builders = self.m.file.read_proto('read {}'.format(config_file),
                                                  file_path, ReleaseBuilders,
                                                  'TEXTPB',
                                                  test_proto=TEST_DATA)
        expiration_date = None
        if is_release_branch:
          # Query chromiumdash to see if the branch is LTS.
          branch_metadata = self.m.cros_schedule.json_to_proto(
              self.m.cros_schedule.fetch_chromiumdash_schedule(
                  start_mstone=milestone, fetch_n=1)).mstones[0]
          if branch_metadata.ltr_last_refresh_date and branch_metadata.ltr_last_refresh_date.ToSeconds(
          ):
            expiration_date = ReleaseBuilder.Date(
                value=(branch_metadata.ltr_last_refresh_date.ToDatetime() +
                       datetime.timedelta(days=14)).strftime("%Y-%m-%d"))
        else:
          # Default expiration date for stabilize branches is 6 months.
          date = datetime.datetime.today() + datetime.timedelta(days=30 * 6)
          expiration_date = ReleaseBuilder.Date(value=date.strftime("%Y-%m-%d"))
          extra_text = (
              '\nThis CL defines release builders for this stabilize branch for'
              ' use with `cros try`. If you do not need `cros try` support,'
              ' consider abandoning this CL.\n')

        # Append new builder for specified branch.
        new_builder = ReleaseBuilder(
            milestone=ReleaseBuilder.Milestone(branch_name=branch,
                                               number=milestone),
            expiration_date=expiration_date)
        release_builders = ReleaseBuilders(
            builders=list(release_builders.builders) + [new_builder])
        release_builders = self._prune_builders(release_builders)
        self.m.file.write_proto('write {}'.format(config_file), file_path,
                                release_builders, 'TEXTPB')

        # Regenerate config.
        self.m.step('./regenerate_configs.sh', ['./regenerate_configs.sh'])

    with self.m.step.nest('create CL'):
      with self.m.context(cwd=workpath):
        # Checkout git branches via repo so they track correctly.
        self.m.repo.start('brancher', projects=[self.CONFIG_PROJECT])
        proj_path = project_path[self.CONFIG_PROJECT]
        commit_lines = [
            'Update config to include {}'.format(branch),
            '',
            'Generated by brancher, see {} for job details.'.format(
                self.m.buildbucket.build_url()),
            '{}'.format(extra_text),
            'BUG=None',
            'TEST=None',
        ]
        commit_message = '\n'.join(commit_lines) + '\n'
        self._create_change(self.CONFIG_PROJECT, proj_path, commit_message)

    if is_release_branch:
      with self.m.step.nest('update R%d chromite android config' % milestone):
        chromite_path = project_path[self.LEGACY_CONFIG_PROJECT]
        with self.m.context(cwd=chromite_path):
          with self.m.git.head_context():
            self.m.git.fetch('cros', refs=[branch])
            self.m.git.checkout(branch)

            self.m.step('update ANDROID_PI_BUILD_BRANCH', [
                'sed', '-i',
                's/git_pi-arc/git_pi-arc-m%d/g' % milestone, CHROMITE_ANDROID
            ])
            self.m.step('update ANDROID_VMRVC_BUILD_BRANCH', [
                'sed', '-i',
                's/git_rvc-arc/git_rvc-arc-m%d/g' % milestone, CHROMITE_ANDROID
            ])
            commit_lines = [
                'Point M{0} ARC to pi-arc-m{0} and rvc-arc-m{0}'.format(
                    milestone),
                '',
                'Generated by brancher, see {} for job details.'.format(
                    self.m.buildbucket.build_url()),
                '',
                'BUG=None',
                'TEST=None',
            ]
            commit_message = '\n'.join(commit_lines) + '\n'
            self._create_change(self.LEGACY_CONFIG_PROJECT, chromite_path,
                                commit_message)
