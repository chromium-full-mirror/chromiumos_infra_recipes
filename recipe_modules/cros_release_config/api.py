# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for managing release config."""

from recipe_engine import recipe_api
import re

from PB.chromiumos.common import ReleaseBuilder, ReleaseBuilders

LEGACY_CONFIG = "config/chromeos_config.py"
CONFIG = "release/release_builders.textpb"

LEGACY_RELEASE_BLOCK_TEMPLATE = """
      ('{}',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""

LEGACY_CONFIG_TEST_DATA = """
  ...
  # Start of RELEASES
  RELEASES = [
      ('release-R89-13729.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),

      ('release-R88-13597.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
  ]
  # End of RELEASES
  ...
"""


class CrosReleaseConfigApi(recipe_api.RecipeApi):
  LEGACY_CONFIG_PROJECT = "chromiumos/chromite"
  CONFIG_PROJECT = "chromeos/infra/config"

  def __init__(self, properties, **kwargs):
    super(CrosReleaseConfigApi, self).__init__(**kwargs)
    self._reviewers = properties.reviewers
    self._ccs = properties.ccs

  def _extract_milestone(self, release_branch):
    res = re.search(r'release-R(\d+)-\d+.B', release_branch)
    if res:
      return int(res.group(1))
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
          used_hours.add(int(hour))
    # TODO(crbug/1122854): This will eventually be triggered by the chromeos-chrome ebuild uprev.
    schedule = '0 4 * * *'
    for hour in range(24):
      if hour not in used_hours:
        schedule = '0 %d * * *' % hour
        break
    return schedule

  def update_config(self, release_branch):
    """Creates CLs updating appropriate config files to include new release branch.

    While Rubik is being turned-up, this endpoint modifies both the legacy config in chromite
    as well as the Rubik starlark config in infra/config.

    Args:
    release_branch (str): Release branch, typically of the form "release-R89-13729.B".

    """
    workpath = self.m.cros_source.workspace_path

    projects = [self.LEGACY_CONFIG_PROJECT, self.CONFIG_PROJECT]
    project_path = {}

    with self.m.step.nest('validate release_branch') as presentation:
      milestone = self._extract_milestone(release_branch)
      if not milestone:
        presentation.status = self.m.step.FAILURE
        presentation.step_next = "bad release_branch"
        return

    # TODO(b/177487002): Add support for auto-submit.
    with self.m.step.nest('validate reviewers') as presentation:
      if not self._reviewers:
        presentation.status = self.m.step.FAILURE
        presentation.step_next = "no reviewers specified"
        return

    with self.m.step.nest('get project info') as presentation:
      with self.m.context(cwd=workpath):
        project_infos = self.m.repo.project_infos(projects=projects)
        for project in project_infos:
          project_path[project.name] = workpath.join(project.path)

    with self.m.step.nest('update legacy config'):
      legacy_path = project_path[self.LEGACY_CONFIG_PROJECT]
      with self.m.context(cwd=legacy_path):
        file_path = legacy_path.join(LEGACY_CONFIG)
        contents = self.m.file.read_raw('read {}'.format(LEGACY_CONFIG),
                                        file_path,
                                        test_data=LEGACY_CONFIG_TEST_DATA)

        p = re.compile(r'RELEASES = \[\n')
        contents = p.sub(
            "RELEASES = [{}\n".format(
                LEGACY_RELEASE_BLOCK_TEMPLATE.format(release_branch)), contents)
        self.m.file.write_raw('write {}'.format(LEGACY_CONFIG), file_path,
                              contents)

    with self.m.step.nest('update config'):
      config_path = project_path[self.CONFIG_PROJECT]
      with self.m.context(cwd=config_path):
        file_path = config_path.join(CONFIG)

        release_builders = self.m.file.read_proto(
            'read {}'.format(CONFIG), file_path, ReleaseBuilders, 'TEXTPB',
            test_proto=ReleaseBuilders(builders=[
                ReleaseBuilder(
                    milestone=ReleaseBuilder.Milestone(
                        branch_name='release-bar.B', number=1),
                    build_schedule="0 8 * * *"),
                ReleaseBuilder(
                    milestone=ReleaseBuilder.Milestone(
                        branch_name='release-baz.B', number=2),
                    build_schedule="0 9 * * *"),
            ]))
        # Append new builder for specified branch.
        new_builder = ReleaseBuilder(
            milestone=ReleaseBuilder.Milestone(branch_name=release_branch,
                                               number=milestone),
            build_schedule=self._get_builder_schedule(release_builders))
        release_builders = ReleaseBuilders(
            builders=list(release_builders.builders) + [new_builder])
        self.m.file.write_proto('write {}'.format(CONFIG), file_path,
                                release_builders, 'TEXTPB')

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
              self.m.git.add([LEGACY_CONFIG])
            elif project == self.CONFIG_PROJECT:
              self.m.git.add([CONFIG])
            else:
              continue  # pragma: nocover
            self.m.git.commit(commit_message)
          self.m.gerrit.create_change(proj_path, reviewers=self._reviewers)
