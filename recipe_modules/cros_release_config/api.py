# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for managing release config."""

from collections import namedtuple
from datetime import datetime
import re

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.common import ReleaseBuilder, ReleaseBuilders

LEGACY_CONFIG = "config/chromeos_config.py"
CONFIG = "release/release_builders.textpb"

LEGACY_RELEASE_BLOCK_TEMPLATE = """
      ('{}',
       ['kevin-android-pi-pre-flight-branch',
        'hatch-android-rvc-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""

TEST_DATA = ReleaseBuilders(builders=[
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='main', number=-1),
        build_schedule="0 1 * * *"),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R01-00001.B',
                                           number=1),
        build_schedule="0 8 * * *"),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R02-00002.B',
                                           number=2),
        build_schedule="0 9 * * *"),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R03-00003.B',
                                           number=3),
        build_schedule="0 * * * *"),
    ReleaseBuilder(
        milestone=ReleaseBuilder.Milestone(branch_name='release-R40-00040.B',
                                           number=40),
        build_schedule="0 11 * * *", expiration_date=ReleaseBuilder.Date(
            value='2100-01-01')),
])

RELEASE_BRANCH_REGEX = r'release-R(\d+)-\d+.B'


class CrosReleaseConfigApi(recipe_api.RecipeApi):
  LEGACY_CONFIG_PROJECT = "chromiumos/chromite"
  CONFIG_PROJECT = "chromeos/infra/config"

  def __init__(self, properties, **kwargs):
    super(CrosReleaseConfigApi, self).__init__(**kwargs)
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
    return list(map(lambda k: k.email, people))

  def _get_builder_expiration_date(self, builder):
    """Get the expiration date for the builder.

    Returns none if the expiration date is not set or is malformatted.

    Args:
    builder (ReleaseBuilder): builder in question
    """
    try:
      return datetime.strptime(builder.expiration_date.value, "%Y-%m-%d")
    except ValueError:
      return None

  def _get_builder_schedule(self, existing_builders):
    """Get a builder schedule for a new builder (in the form of a crontab).

    If possible, choose an hour that is not currently in use to better distribute load.

    Args:
    existing_builders (ReleaseBuilders): existing release builders.
    """
    used_hours = set()
    for b in existing_builders.builders:
      cron_components = b.build_schedule.split()
      if len(cron_components) == 5:
        for hour in cron_components[1].split(','):
          # We are supporting '*', so if the hour can't be parsed into an int,
          # ignore it for our purposes.
          try:
            hour = int(hour)
            used_hours.add(hour)
          except ValueError:
            pass
    # TODO(crbug/1122854): This will eventually be triggered by the chromeos-chrome ebuild uprev.
    schedule = '0 4 * * *'
    for hour in range(24):
      if hour not in used_hours:
        schedule = '0 %d * * *' % hour
        break
    return schedule

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
        pinned_by_date = expiration_date > datetime.now()
      if re.match(RELEASE_BRANCH_REGEX,
                  builder.milestone.branch_name) and not pinned_by_date:
        true_release_builders.append(builder)
      else:
        to_keep.append(builder)

    to_keep.extend(
        sorted(true_release_builders, key=lambda k: k.milestone.number,
               reverse=True)[:self._keep_n_milestones])
    return ReleaseBuilders(builders=to_keep)

  def _prune_legacy_config(self, file_contents):
    """ Prune the list of builders in legacy config.

    Prunes down to keep_n_milestones builders for release branches.
    Builders preceded by a '# BOT-TAG:NO_PRUNE' comment will not be counted
    towards the quota, nor will non-release branches (e.g. main).

    Args:
    file_contents (string): Legacy config file contents.
    """
    if not self._keep_n_milestones:
      return file_contents

    with self.m.step.nest("prune legacy config"):
      LEGACY_REGEX = r'# BOT-TAG:RELEASES_START.*\n'\
        r'(?P<releases>(\n|.)*)# BOT-TAG:RELEASES_END'
      res = re.search(LEGACY_REGEX, file_contents)
      if not res:
        raise StepFailure("malformated legacy config")

      # Isolate 'RELEASES = [' section.
      legacy_block = res.group('releases').strip()
      if not legacy_block.startswith(
          "RELEASES = [") or not legacy_block.endswith("]"):
        raise StepFailure("malformated legacy config")

      builder_block = legacy_block[len("RELEASES = ["):-1].strip()
      builders = map(lambda x: x, builder_block.split("),"))
      # Filter out empty strings.
      builders = filter(lambda x: x, builders)
      # Add back ), to end of blocks.
      builders = list(map(lambda x: x + "),", builders))

      def get_builder_info(builder_text):
        # This regex collects any leading comments as well as the branch name
        # (which should be the first item in the tuple).
        BRANCH_NAME_REGEX = r'(?P<cmts>(#.*\s*)*)\s*\n*\(\'(?P<branch>.*)\''
        res = re.search(BRANCH_NAME_REGEX, builder_text)
        if not res:
          return None
        comment_block = (res.group('cmts') or "").strip()
        comments = list(map(lambda x: x.strip(), comment_block.split('\n')))
        BuilderInfo = namedtuple('BuilderInfo',
                                 ['comments', 'branch_name', 'milestone'])
        branch_name = res.group('branch')
        milestone = -1
        if re.match(RELEASE_BRANCH_REGEX, branch_name):
          milestone = self._extract_milestone(branch_name)
        # e.g. (['# foo', '# BOT-TAG:NO_PRUNE'], 'release-R88-13597.B', 88)
        return BuilderInfo(comments=comments, branch_name=branch_name,
                           milestone=milestone)

      pruneable = []
      builder_info = {}
      for builder in builders:
        info = get_builder_info(builder)
        if not info:
          raise StepFailure("malformated legacy config")
        builder_info[builder] = info
        if info.milestone > 0 and "# BOT-TAG:NO_PRUNE" not in info.comments:
          pruneable.append(builder)

      if len(pruneable) <= self._keep_n_milestones:
        return file_contents

      pruneable = sorted(pruneable, key=lambda b: builder_info[b].milestone)
      # Prune appopriate number of builders in ascending order of milestone.
      for i in range(len(pruneable) - self._keep_n_milestones):
        new_legacy_block = legacy_block.replace(pruneable[i], '')
        file_contents = file_contents.replace(legacy_block, new_legacy_block)
        legacy_block = new_legacy_block
      # Clean up leading newlines in case we pruned the leading block.
      file_contents = re.sub(r'RELEASES = \[(\s*\n)*', 'RELEASES = [\n',
                             file_contents)

      return file_contents

  def update_config(self, release_branch):
    """Creates CLs updating config file to include new release branch.

    While Rubik is being turned-up, this endpoint modifies both the legacy
    config in chromite as well as the Rubik starlark config in infra/config.

    Args:
    release_branch (str): Release branch, e.g. "release-R89-13729.B".

    """
    workpath = self.m.cros_source.workspace_path

    projects = [self.LEGACY_CONFIG_PROJECT, self.CONFIG_PROJECT]
    project_path = {}

    with self.m.step.nest('validate release_branch'):
      milestone = self._extract_milestone(release_branch)
      if not milestone:
        raise StepFailure("bad release_branch")

    with self.m.step.nest('validate CL settings'):
      if not self._reviewers and not self._auto_submit:
        raise StepFailure("no reviewers specified and auto submit is false")

    with self.m.step.nest('get project info'):
      with self.m.context(cwd=workpath):
        project_infos = self.m.repo.project_infos(projects=projects)
        for project in project_infos:
          project_path[project.name] = workpath.join(project.path)

    with self.m.step.nest('update legacy config'):
      legacy_path = project_path[self.LEGACY_CONFIG_PROJECT]
      with self.m.context(cwd=legacy_path):
        file_path = legacy_path.join(LEGACY_CONFIG)
        contents = self.m.file.read_raw('read {}'.format(LEGACY_CONFIG),
                                        file_path)

        p = re.compile(r'RELEASES = \[\n')
        contents = p.sub(
            "RELEASES = [{}\n".format(
                LEGACY_RELEASE_BLOCK_TEMPLATE.format(release_branch)), contents)
        contents = self._prune_legacy_config(contents)
        self.m.file.write_raw('write {}'.format(LEGACY_CONFIG), file_path,
                              contents)

        # Refresh generated files.
        self.m.step('./config/refresh_generated_files',
                    ['./config/refresh_generated_files'])

    with self.m.step.nest('update config'):
      config_path = project_path[self.CONFIG_PROJECT]
      with self.m.context(cwd=config_path):
        file_path = config_path.join(CONFIG)

        release_builders = self.m.file.read_proto('read {}'.format(CONFIG),
                                                  file_path, ReleaseBuilders,
                                                  'TEXTPB',
                                                  test_proto=TEST_DATA)
        # Append new builder for specified branch.
        new_builder = ReleaseBuilder(
            milestone=ReleaseBuilder.Milestone(branch_name=release_branch,
                                               number=milestone),
            build_schedule=self._get_builder_schedule(release_builders))
        release_builders = ReleaseBuilders(
            builders=list(release_builders.builders) + [new_builder])
        # TODO(b/177487002): Add pruning support for legacy config.
        release_builders = self._prune_builders(release_builders)
        self.m.file.write_proto('write {}'.format(CONFIG), file_path,
                                release_builders, 'TEXTPB')

        # Regenerate config.
        self.m.step('./regenerate_configs.sh', ['./regenerate_configs.sh'])

    with self.m.step.nest('create CLs'):
      with self.m.context(cwd=workpath):
        # Checkout git branches via repo so they track correctly.
        self.m.repo.start('brancher', projects=projects)
        for project in projects:
          proj_path = project_path[project]
          commit_lines = [
              'Update config to include {}'.format(release_branch),
              '',
              'Generated by brancher, see {} for job details.'.format(
                  self.m.buildbucket.build_url()),
              '',
              'BUG=None',
              'TEST=None',
          ]
          commit_message = '\n'.join(commit_lines) + '\n'
          with self.m.step.nest(
              'commit in {}'.format(project)), self.m.context(cwd=proj_path):
            if project == self.LEGACY_CONFIG_PROJECT:
              self.m.git.add([project_path[self.LEGACY_CONFIG_PROJECT]])
            elif project == self.CONFIG_PROJECT:
              self.m.git.add([project_path[self.CONFIG_PROJECT]])
            else:
              continue  # pragma: nocover
            self.m.git.commit(commit_message)
          change = self.m.gerrit.create_change(
              proj_path, reviewers=self._get_emails(self._reviewers),
              ccs=self._get_emails(self._ccs))
          if self._auto_submit:
            self.m.gerrit.set_change_labels(
                change, {
                    self.m.gerrit.Label.BOT_COMMIT: 1,
                    self.m.gerrit.Label.COMMIT_QUEUE: 2,
                })
