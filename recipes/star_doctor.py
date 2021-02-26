# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

import functools
from google.protobuf.text_format import MessageToString

from recipe_engine import post_process

from PB.recipes.chromeos.star_doctor import (StarDoctorProperties,
                                             RemoteConfigFile)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'cros_schedule',
    'gerrit',
    'git',
    'git_cl',
]

CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'
INTERNAL_HOST = 'https://chrome-internal.googlesource.com'
EXTERNAL_HOST = 'https://chromium.googlesource.com'
INTERNAL_REVIEW_HOST = 'https://chrome-internal-review.googlesource.com'
EXTERNAL_REVIEW_HOST = 'https://chromium-review.googlesource.com'
INFRA_CONFIG_PROJECT = 'chromeos/infra/config'
SUITE_SCHEDULER_PROJECT = 'chromiumos/infra/suite_scheduler'
STARDOCTOR_TOPIC = 'StarDoctor'
CONFIG_UPDATE_HASHTAG = 'config_update'
INFRA_CONFIG_URL = '{}/{}'.format(INTERNAL_HOST, INFRA_CONFIG_PROJECT)
SUITE_SCHEDULER_URL = '{}/{}'.format(EXTERNAL_HOST, SUITE_SCHEDULER_PROJECT)
CONFIG_INTERNAL_URL = 'https://chrome-internal.googlesource.com/chromeos/config-internal'

PROPERTIES = StarDoctorProperties


def RunSteps(api, properties):
  with api.step.nest('set up'):
    infra_config_dir = _get_clone(api, INFRA_CONFIG_URL)
    ss_dir = _get_clone(api, SUITE_SCHEDULER_URL)
    # We don't really need the full clone yet. But, it is assumed that configs
    # will need to be regenerated here at some point.
    config_internal_dir = api.path.mkdtemp()
    api.step('clone config-internal', [
        'git', 'clone', CONFIG_INTERNAL_URL, '--depth', '1', config_internal_dir
    ])
    # https://crbug.com/1154700 caused regular git clone to fail here.
    # config_internal_dir = _get_clone(api, CONFIG_INTERNAL_URL)

  remote_config_files = properties.remote_config_files
  # If remote_config_files is not specified, build them based on the ge_bucket
  # and branches properties. Note that if remote_config_files is specified,
  # ge_bucket and branches should not be.
  if not remote_config_files:
    remote_config_files.add(
        bucket_name=properties.ge_bucket,
        object_name='build_config.ToT.json',
        dest_path='release/ge_jsons/build_config.ToT.json',
    )

    for branch in properties.branches:
      branched_config = 'build_config.release-{}.json'.format(branch)
      remote_config_files.add(
          bucket_name=properties.ge_bucket,
          object_name=branched_config,
          dest_path='release/ge_jsons/{}'.format(branched_config),
      )
  else:
    if properties.ge_bucket or properties.branches:
      raise ValueError(
          'ge_bucket and branches cannot be set if remote_config_files is set.')

  with api.step.nest('generate binary config'):
    with api.step.nest('copy remote configs') as presentation:
      for remote_config_file in remote_config_files:
        api.gsutil.download(
            remote_config_file.bucket_name, remote_config_file.object_name,
            infra_config_dir.join(remote_config_file.dest_path),
            name='download {}/{}'.format(
                remote_config_file.bucket_name,
                remote_config_file.object_name,
            ))
    with api.step.nest('fetch chromiumos schedule') as presentation:
      # Stay 10 milestones ahead.
      schedule_fname = api.path.join(infra_config_dir,
                                     'release/schedule/schedule.textproto')
      last_mstone = api.cros_schedule.get_last_branched_mstone_n()
      fetch_n = last_mstone - 70 + 10
      mstones = api.cros_schedule.json_to_proto(
          api.cros_schedule.fetch_chromiumdash_schedule(start_mstone=70,
                                                        fetch_n=fetch_n))
      api.file.write_text('write textproto', schedule_fname,
                          MessageToString(mstones))
    # We need lucicfg from depot_tools.
    with api.depot_tools.on_path():
      # We need protoc from cipd.
      cipd_dir = api.path.mkdtemp()
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/tools/protoc/linux-amd64',
                       'protobuf_version:v3.11.4')
      api.cipd.ensure(cipd_dir, pkgs)
      with api.context(**{'env_suffixes': {'PATH': [cipd_dir]}}):
        with api.context(cwd=infra_config_dir):
          api.step('regenerate configs',
                   ['/bin/bash', 'regenerate_configs.sh', '-b'], timeout=3 * 60)

    with api.step.nest('copy INI configs') as presentation:
      dest_ini = api.path.join(ss_dir, 'generated_configs')
      orig_ini = api.path.join(config_internal_dir, 'test', 'suite_scheduler',
                               'generated')
      api.file.copy('lab_config.ini', api.path.join(orig_ini, 'lab_config.ini'),
                    dest_ini)
      api.file.copy('suite_scheduler.ini',
                    api.path.join(orig_ini, 'suite_scheduler.ini'), dest_ini)

  with api.step.nest('commit changes') as presentation:
    if not properties.commit_changes:
      presentation.step_text = 'not configured to commit changes'
      return

    infra_config_labels = ['l=Bot-Commit+1', 'l=Commit-Queue+2']
    ss_labels = infra_config_labels + ['l=Verified+1']
    _commit_changed_files(api, infra_config_dir, INFRA_CONFIG_PROJECT,
                          infra_config_labels)
    _commit_changed_files(api, ss_dir, SUITE_SCHEDULER_PROJECT, ss_labels)


def _abandon_old_changes(api, project):
  # Abandon older changes that never landed. These are changes
  # created by stardoctor in previous iterations and did not merge
  # for *some* reason.
  host = (
      INTERNAL_REVIEW_HOST
      if project.startswith('chromeos') else EXTERNAL_REVIEW_HOST)
  changes = api.gerrit.query_changes(host, [
      ('project', project),
      ('owner', CI_PROD_SERVICE_ACCOUNT),
      ('topic', STARDOCTOR_TOPIC),
      ('hashtag', CONFIG_UPDATE_HASHTAG),
      ('status', 'open'),
  ])
  for change in changes:
    api.gerrit.abandon_change(change)


def _get_clone(api, repo_url):
  repo_dir = api.path.mkdtemp()
  api.git.clone(repo_url, target_path=repo_dir, timeout_sec=3 * 60)
  return repo_dir


def _commit_changed_files(api, repo_dir, project, labels):
  """Commit and push changed files.

  Args:
    repo_dir(Path): Path to the repository to push.
    project(str): Project name of the repo.
    labels([str]): Submission labels for the project.
  """
  host = (INTERNAL_HOST if project.startswith('chromeos') else EXTERNAL_HOST)
  _abandon_old_changes(api, project)
  repo_url = '{}/{}'.format(host, project)
  commit_lines = [
      'Automatic config update',
      'Generated by StarDoctor, see {} for the recipe.'.format(
          api.buildbucket.build_url()),
      'BUG=None\nTEST=regenerated configs',
  ]
  commit_msg = '\n\n'.join(commit_lines)
  step_name = 'committing to {}'.format(project)

  with api.step.nest(step_name) as presentation:
    with api.context(cwd=repo_dir):
      branch = api.git.current_branch()
      changed_files = api.git.get_working_dir_diff_files()
      if not changed_files:  # pragma: nocover
        presentation.step_text = 'no files changed'
        return None
      api.git.add(changed_files)
      api.git.commit(commit_msg)
      # Upload using git cl so that we can add topic and hashtags.
      # These are used to abandon unlanded changes later.
      api.git_cl.upload(topic=STARDOCTOR_TOPIC,
                        hashtags=[CONFIG_UPDATE_HASHTAG])
      gerrit_change_url = api.git_cl.status(
          field='url', fast=True,
          step_test_data=functools.partial(api.raw_io.test_api.stream_output,
                                           'https://crrev.com/i/somenumber'))
      api.git.push(repo_url,
                   'HEAD:refs/for/{}%{}'.format(branch, ','.join(labels)))
      presentation.links['change committed'] = gerrit_change_url


def GenTests(api):
  yield api.test('dont_commit', api.time.seed(1613694623.0),
                 api.properties(commit_changes=False))

  yield api.test(
      'full', api.time.seed(1613694623.0),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']))

  yield api.test(
      'old_and_new_properties_set',
      api.time.seed(1613694623.0),
      api.properties(
          StarDoctorProperties(
              ge_bucket='test_ge_bucket',
              branches=['R9000'],
              remote_config_files=[
                  RemoteConfigFile(
                      bucket_name='test_bucket',
                      object_name='test_object',
                      dest_path='ge/test_object',
                  )
              ],
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       ('.*ge_bucket and branches cannot be set if'
                        ' remote_config_files is set..*')),
      api.post_process(post_process.DropExpectation),
  )
