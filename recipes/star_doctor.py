# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

import base64
from collections import namedtuple
import functools
import json
from google.protobuf.text_format import MessageToString

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.recipes.chromeos.star_doctor import (StarDoctorProperties,
                                             RemoteConfigFile)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
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
    'gitiles',
]

CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'
INTERNAL_HOST_DOMAIN = 'chrome-internal.googlesource.com'
EXTERNAL_HOST_DOMAIN = 'chromium.googlesource.com'
INTERNAL_HOST = 'https://' + INTERNAL_HOST_DOMAIN
EXTERNAL_HOST = 'https://' + EXTERNAL_HOST_DOMAIN
INTERNAL_REVIEW_HOST = 'https://chrome-internal-review.googlesource.com'
EXTERNAL_REVIEW_HOST = 'https://chromium-review.googlesource.com'
INFRA_CONFIG_PROJECT = 'chromeos/infra/config'
SUITE_SCHEDULER_PROJECT = 'chromiumos/infra/suite_scheduler'
STARDOCTOR_TOPIC = 'StarDoctor'
CONFIG_UPDATE_HASHTAG = 'config-update'
INFRA_CONFIG_URL = '{}/{}'.format(INTERNAL_HOST, INFRA_CONFIG_PROJECT)
SUITE_SCHEDULER_URL = '{}/{}'.format(EXTERNAL_HOST, SUITE_SCHEDULER_PROJECT)
CONFIG_INTERNAL_URL = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
TIMELINE_FILENAME = 'release/timeline_configuration.json'

PROPERTIES = StarDoctorProperties

RepoDirs = namedtuple('RepoDirs',
                      ('infra_config', 'suite_scheduler', 'config_internal'))


def RunSteps(api, properties):
  with api.step.nest('set up'):
    _validate_properties(api, properties)
    repo_dirs = _clone_repos(api)
  remote_config_files = _get_remote_config_files(properties)

  with api.step.nest('generate binary config'):
    _copy_remote_configs(api, repo_dirs, remote_config_files)
    _fetch_and_write_chromiumos_schedule(api, repo_dirs)
    _fetch_and_write_keyset_config(api, repo_dirs)
    _update_release_time(api, repo_dirs)
    _regenerate_configs(api, repo_dirs)
    _copy_ini_configs(api, repo_dirs)

  irrelevant_files = set()
  irrelevant_files.add(TIMELINE_FILENAME)
  _commit_all_changes(api, properties, repo_dirs, irrelevant_files)


def _clone_repos(api):
  """Clone any necessary repos.

  Args:
    api: The recipe modules API.

  Returns:
    A namedtuple (RepoDirs) of the local checkout locations.
  """
  infra_config_dir = _get_clone(api, INFRA_CONFIG_URL)
  ss_dir = _get_clone(api, SUITE_SCHEDULER_URL)
  # We don't really need the full clone yet. But, it is assumed that configs
  # will need to be regenerated here at some point.
  # Clone shallowly to avoid running out of storage: see crbug/1154700.
  config_internal_dir = _get_clone(api, CONFIG_INTERNAL_URL, depth=1)
  return RepoDirs(
      infra_config=infra_config_dir,
      suite_scheduler=ss_dir,
      config_internal=config_internal_dir,
  )


def _get_clone(api, repo_url, **kwargs):
  """Create a Git clone in a temporary directory.

  Args:
    api: The recipe modules API.
    repo_url: Full path to the Git repo to clone.
    kwargs: Any other keyword arguments to pass to api.get.clone.

  Returns:
    The path to the newly cloned Git checkout.
  """
  repo_dir = api.path.mkdtemp()
  api.git.clone(repo_url, target_path=repo_dir, **kwargs)
  return repo_dir


def _validate_properties(api, props):
  """Check that the input properties don't contain any contradictions."""
  with api.step.nest('validate properties'):
    if props.remote_config_files and (props.ge_bucket or props.branches):
      raise StepFailure(
          'ge_bucket and branches cannot be set if remote_config_files is set.')


def _get_remote_config_files(properties):
  """Determine remote config files based on input properties.

  If properties.remote_config_files is not specified, build them based on the
  ge_bucket and branches properties. Note that if remote_config_files is
  specified, ge_bucket and branches should not be.

  Args:
    properties (StarDoctorProperties): Input properties to the recipe.

  Returns:
    A list of config files to download from Google Storage.

  Raises:
    StepFailure: If input properties specify remote_config_files and either
      ge_bucket or branches.
  """
  remote_config_files = properties.remote_config_files
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
  return remote_config_files


def _copy_remote_configs(api, repo_dirs, remote_config_files):
  """Download the specified files from gsutil.

  Args:
    api: The recipe modules API.
    repo_dirs: A namedtuple (RepoDirs) containing local checkout locations.
    remote_config_files: List[RemoteConfigFile] representing config files to
      download from Google Storage.
  """
  with api.step.nest('copy remote configs'):
    for remote_config_file in remote_config_files:
      api.gsutil.download(
          remote_config_file.bucket_name, remote_config_file.object_name,
          api.path.join(repo_dirs.infra_config, remote_config_file.dest_path),
          name='download {}/{}'.format(
              remote_config_file.bucket_name,
              remote_config_file.object_name,
          ))


def _fetch_and_write_chromiumos_schedule(api, repo_dirs):
  """Read the release schedule from Cr-, and write it to infra/config."""
  with api.step.nest('fetch chromiumos schedule'):
    # Stay 10 milestones ahead.
    schedule_fname = api.path.join(repo_dirs.infra_config,
                                   'release/schedule/schedule.textproto')
    last_mstone = api.cros_schedule.get_last_branched_mstone_n()
    fetch_n = last_mstone - 70 + 10
    mstones = api.cros_schedule.json_to_proto(
        api.cros_schedule.fetch_chromiumdash_schedule(start_mstone=70,
                                                      fetch_n=fetch_n))
    api.file.write_text('write textproto', schedule_fname,
                        MessageToString(mstones))


def _fetch_and_write_keyset_config(api, repo_dirs):
  """Read release keys from platform, and write it to infra/config."""
  with api.step.nest('fetch and write keyset configuration'):
    keyset_json = api.gitiles.get_file(
        INTERNAL_HOST_DOMAIN, 'chromeos/platform/release-keys',
        'generated/keyset.json', public=False,
        test_output_data=base64.b64encode('{"abc": 123}'))
    # Ensure it's json after all, then write.
    validated_keys = json.dumps(
        json.loads(keyset_json), sort_keys=True, indent=2)
    keyset_fname = api.path.join(repo_dirs.infra_config,
                                 'release/signing/keyset.json')
    api.file.write_text('write keyset json', keyset_fname, validated_keys)


def _update_release_time(api, repo_dirs):
  """Update the infra/config/releases/timeline_configuration.json time field."""
  tl_cfg_fpath = api.path.join(repo_dirs.infra_config, TIMELINE_FILENAME)
  with api.step.nest("update configured release time"):
    step_result = api.json.read(
        'read json', tl_cfg_fpath, step_test_data=lambda: api.json.test_api.
        output({"time": "2021-04-06T16:00:40Z"}))
    tl_cfg = step_result.json.output
    tl_cfg['time'] = api.time.utcnow().strftime("%FT%TZ")
    api.file.write_text('write release channel timeline configuration',
                        tl_cfg_fpath, json.dumps(tl_cfg, indent=2))


def _regenerate_configs(api, repo_dirs):
  """Runs the regenerate_configs.sh script in infra/config."""
  # We need lucicfg from depot_tools.
  with api.depot_tools.on_path():
    # We need protoc from cipd.
    cipd_dir = _ensure_cipd_packages(api)
    with api.context(**{'env_suffixes': {'PATH': [cipd_dir]}}):
      with api.context(cwd=repo_dirs.infra_config):
        api.step('regenerate configs',
                 ['/bin/bash', 'regenerate_configs.sh', '-b'], timeout=3 * 60)


def _ensure_cipd_packages(api):
  """Ensure that any necessary CIPD packages are installed.

  Args:
    api: The recipe modules API.

  Returns:
    The full path to the CIPD directory.
  """
  cipd_dir = api.path.mkdtemp()
  pkgs = api.cipd.EnsureFile()
  pkgs.add_package('infra/tools/protoc/linux-amd64', 'protobuf_version:v3.11.4')
  api.cipd.ensure(cipd_dir, pkgs)
  return cipd_dir


def _copy_ini_configs(api, repo_dirs):
  """Copy .ini files from internal config to the suite_scheduler repo.

  Args:
    api: The recipe modules API.
    repo_dirs: A namedtuple (RepoDirs) containing local checkout locations.
  """
  with api.step.nest('copy INI configs'):
    orig_dir = api.path.join(repo_dirs.config_internal, 'test',
                             'suite_scheduler', 'generated')
    dest_dir = api.path.join(repo_dirs.suite_scheduler, 'generated_configs')
    api.file.copy('lab_config.ini', api.path.join(orig_dir, 'lab_config.ini'),
                  dest_dir)
    api.file.copy('suite_scheduler.ini',
                  api.path.join(orig_dir, 'suite_scheduler.ini'), dest_dir)
    api.file.copy('rubik_config.ini',
                  api.path.join(orig_dir, 'rubik_config.ini'), dest_dir)


def _commit_all_changes(api, properties, repo_dirs, irrelevant_files=None):
  """Commit and push changed files in all repos.

  Args:
    api: The recipe modules API.
    properties: StarDoctorProperties, a proto containing input properties.
    repo_dirs: A namedtuple (RepoDirs) containing local checkout locations.
    irrelevant_files(set(files)): Files that alone, shouldn't trigger a commit.
  """
  with api.step.nest('commit changes') as presentation:
    if not properties.commit_changes:
      presentation.step_text = 'not configured to commit changes'
      return

    infra_config_labels = {
        api.gerrit.Label.BOT_COMMIT: 1,
        api.gerrit.Label.COMMIT_QUEUE: 2
    }
    ss_labels = {
        api.gerrit.Label.BOT_COMMIT: 1,
        api.gerrit.Label.COMMIT_QUEUE: 2,
        api.gerrit.Label.VERIFIED: 1,
    }
    _commit_repo_changes(api, repo_dirs.infra_config, INFRA_CONFIG_PROJECT,
                         infra_config_labels, irrelevant_files=irrelevant_files)
    _commit_repo_changes(api, repo_dirs.suite_scheduler,
                         SUITE_SCHEDULER_PROJECT, ss_labels,
                         irrelevant_files=irrelevant_files)


def _commit_repo_changes(api, repo_dir, project, labels, irrelevant_files=None):
  """Commit and push changed files in one repo.

  Args:
    repo_dir(Path): Path to the repository to push.
    project(str): Project name of the repo.
    labels([str]): Submission labels for the project.
    irrelevant_files(set(files)): Files that alone, shouldn't trigger a commit.
  """
  irrelevant_files = irrelevant_files or set()
  _abandon_old_changes(api, project)
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

      # If there aren't leftover files when we subtract the irrelevant ones.
      if not set(changed_files) - irrelevant_files:
        presentation.step_text = 'no relevant files changed'
        return None

      api.git.add(changed_files)
      api.git.commit(commit_msg)
      # Upload using git cl so that we can add topic and hashtags.
      # These are used to abandon unlanded changes later.
      change = api.gerrit.create_change(project, topic=STARDOCTOR_TOPIC,
                                        hashtags=[CONFIG_UPDATE_HASHTAG],
                                        ref=api.git.get_branch_ref(branch),
                                        project_path=repo_dir)
      api.gerrit.set_change_labels_remote(change, labels)
      gerrit_change_url = api.git_cl.status(
          field='url', fast=True,
          step_test_data=functools.partial(api.raw_io.test_api.stream_output,
                                           'https://crrev.com/i/somenumber'))
      presentation.links['change uploaded'] = gerrit_change_url


def _abandon_old_changes(api, project):
  """Abandon older changes that never landed.

  These are changes created by previous iterations of StarDoctor, which did not
  merge for some reason.

  Args:
    api: The recipe modules API.
    project: Project name of the repo.
  """
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


def GenTests(api):
  yield api.test('dont_commit', api.time.seed(1613694623.0),
                 api.properties(commit_changes=False))

  yield api.test(
      'full', api.time.seed(1613694623.0),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']))

  yield api.test(
      'only_irrelevant', api.time.seed(1613694623.0),
      api.step_data(
          'commit changes.committing to chromeos/infra/config.git status',
          stdout=api.raw_io.output(' M release/timeline_configuration.json')),
      api.properties(commit_changes=True, ge_bucket='test_ge_bucket',
                     branches=['R9000']),
      api.post_check(
          post_process.DoesNotRun,
          'commit changes.committing to chromeos/infra/config.git commit'))

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
      api.post_process(post_process.StepFailure, 'set up.validate properties'),
      api.post_process(post_process.ResultReasonRE,
                       ('.*ge_bucket and branches cannot be set if'
                        ' remote_config_files is set..*')),
      api.post_process(post_process.DropExpectation),
  )
