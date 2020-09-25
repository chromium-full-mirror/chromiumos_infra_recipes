# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

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
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'gerrit',
    'git',
]

INFRA_CONFIG_URL = 'https://chrome-internal.googlesource.com/chromeos/infra/config'
SUITE_SCHEDULER_URL = 'https://chromium.googlesource.com/chromiumos/infra/suite_scheduler'
CONFIG_INTERNAL_URL = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'

PROPERTIES = StarDoctorProperties


def RunSteps(api, properties):
  with api.step.nest('set up'):
    infra_config_dir = _get_clone(api, INFRA_CONFIG_URL)
    ss_dir = _get_clone(api, SUITE_SCHEDULER_URL)
    # We don't really need the full clone yet. But, it is assumed that configs
    # will need to be regenerated here at some point.
    config_internal_dir = _get_clone(api, CONFIG_INTERNAL_URL)

  remote_config_files = properties.remote_config_files
  # If remote_config_files is not specified, build them based on the ge_bucket
  # and branches properties. Note that if remote_config_files is specified,
  # ge_bucket and branches should not be.
  if not remote_config_files:
    remote_config_files.add(
        bucket_name=properties.ge_bucket,
        object_name='build_config.ToT.json',
        dest_path='goldeneye/build_config.ToT.json',
    )

    for branch in properties.branches:
      branched_config = 'build_config.release-{}.json'.format(branch)
      remote_config_files.add(
          bucket_name=properties.ge_bucket,
          object_name=branched_config,
          dest_path='goldeneye/{}'.format(branched_config),
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
    changes = []
    if not properties.commit_changes:
      presentation.step_text = 'not configured to commit changes'
      return
    infra_config_labels = ['l=Bot-Commit+1', 'l=Commit-Queue+2']
    pushed = _commit_changed_files(api, 'committing to infra-config',
                                   infra_config_dir, INFRA_CONFIG_URL,
                                   infra_config_labels)
    if pushed:
      changes += _get_change(api, 'chromeos/infra/config', internal=True)

    ss_labels = infra_config_labels + ['l=Verified+1']
    pushed = _commit_changed_files(api, 'committing to suite-scheduler', ss_dir,
                                   SUITE_SCHEDULER_URL, ss_labels)
    if pushed:
      changes += _get_change(api, 'chromiumos/infra/suite_scheduler')

    for i in range(len(changes)):
      presentation.links['change #{}'.format(i + 1)] = changes[i]


def _get_change(api, project, internal=False):
  host = ('https://chrome-internal-review.googlesource.com'
          if internal else 'https://chromium-review.googlesource.com')
  changes = api.gerrit.query_changes(host, [
      ('project', project),
      ('owner', CI_PROD_SERVICE_ACCOUNT),
      ('status', 'open'),
  ])
  if len(changes) < 1:  # pragma: nocover
    return []
  url_tag = 'i' if internal else 'c'
  return ['https://crrev.com/{}/{}'.format(url_tag, changes[0].change)]


def _get_clone(api, repo_url):
  repo_dir = api.path.mkdtemp()
  api.git.clone(repo_url, target_path=repo_dir, timeout_sec=3 * 60)
  return repo_dir


def _commit_changed_files(api, step_name, repo_dir, repo_url, labels):
  """Commit and push changed files.
  
  Args:
    step_name(str): Name of the step.
    repo_dir(Path): Path to the repository to push.
    repo_url(str): Gerrit URL of the repo.
    labels([str]): Submission labels for the project.

  Returns: Boolean, indicating whether the change was pushed.
  """
  commit_lines = [
      'Automatic config update',
      'Generated by StarDoctor, see {} for the recipe.'.format(
          api.buildbucket.build_url()),
      'BUG=None\nTEST=regenerated configs',
  ]
  commit_msg = '\n\n'.join(commit_lines)

  with api.step.nest(step_name) as presentation:
    with api.context(cwd=repo_dir):
      changed_files = api.git.get_working_dir_diff_files()
      if not changed_files:  # pragma: nocover
        presentation.step_text = 'no files changed'
        return False
      api.git.add(changed_files)
      api.git.commit(commit_msg)
      api.git.push(repo_url, 'HEAD:refs/for/master%{}'.format(','.join(labels)))
      return True


def GenTests(api):
  yield api.test('dont_commit', api.properties(commit_changes=False))

  yield api.test(
      'full',
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']))

  yield api.test(
      'old_and_new_properties_set',
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
