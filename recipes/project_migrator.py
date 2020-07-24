# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run on changes to model.yaml and HWID databases.

Copies the changed files into a project-local location and regenerates merged
configuration data.
"""

# This builder is meant to be triggered off of single file changes after they've
# made it to gitiles.  The input properties tell us where the public/private
# yaml files are (if any) and what key to use in the HWID database.
#
# When run, the model.yaml and HWID repos are cloned, the data merged and copied
# over to the destination repo.  As long as the pending diff is non-empty a new
# commit is made with the merged data and updated configs.

from PB.recipes.chromeos.project_migrator import ProjectMigratorProperties
from recipe_engine import post_process

# Recipe dependencies
DEPS = [
    'gerrit',
    'git',
    'git_txn',
    'gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = ProjectMigratorProperties

# Repo URL configuration
CROS_HWID_REPO = 'https://chrome-internal.googlesource.com/chromeos/chromeos-hwid'
CROS_CONFIG_REPO = 'https://chromium.googlesource.com/chromiumos/config'

# Source and destination config files
SRC_CONFIG = 'generated/config.jsonproto'
DST_CONFIG = 'generated/joined.jsonproto'

JOIN_SCRIPT_PATH = 'payload_utils/join_config_payloads.py'


def require(cond, message):
  """Require a given condition be true or throw a ValueError."""
  if not cond:
    raise ValueError(message)


def RunSteps(api, properties):
  require(properties.dest_repo, 'Destination repo must be specified.')

  # Defines paths to which to clone repos.
  cros_config_path = api.path['start_dir'].join('config')
  dest_repo_path = api.path['start_dir'].join('dest')
  public_repo_path = api.path['start_dir'].join('public')
  private_repo_path = api.path['start_dir'].join('private')
  hwid_repo_path = api.path['start_dir'].join('hwid')

  # Destination path configuration
  dest_file_path = dest_repo_path.join('imported')
  dest_hwid_path = dest_file_path.join('hwid')
  dest_yaml_path = dest_file_path.join('model.yaml')

  # Clone config repo
  with api.step.nest('cloning config repo'):
    api.git.clone(CROS_CONFIG_REPO, target_path=cros_config_path)

  # Clone source repos.
  have_work = False
  if properties.HasField('public_yaml'):
    have_work = True
    with api.step.nest('cloning public overlay'):
      api.git.clone(properties.public_yaml.repo, target_path=public_repo_path)

  if properties.HasField('private_yaml'):
    have_work = True
    with api.step.nest('cloning private overlay'):
      api.git.clone(properties.private_yaml.repo, target_path=private_repo_path)

  if properties.hwid_key:
    have_work = True
    with api.step.nest('cloning hwid repo'):
      api.git.clone(CROS_HWID_REPO, target_path=hwid_repo_path)

  with api.step.nest('Checking files to update') as presentation:
    if not have_work:
      raise ValueError(
          'Neither model.yaml nor HWID was configured, this is a noop!')

  # Clone the destination repo.
  with api.step.nest('cloning destination repo'):
    api.git.clone(properties.dest_repo, target_path=dest_repo_path)

  # And copy files over
  with api.context(cwd=dest_repo_path):
    api.file.ensure_directory('ensure %s directory exists' % dest_file_path,
                              dest_file_path)

    if properties.HasField('public_yaml'):
      file_path = dest_file_path.join('public_model.yaml')
      api.file.copy('copy public model.yaml',
                    public_repo_path.join(properties.public_yaml.path),
                    file_path)
      api.git.add([file_path])

    if properties.HasField('private_yaml'):
      file_path = dest_file_path.join('private_model.yaml')
      api.file.copy('copy private model.yaml',
                    private_repo_path.join(properties.private_yaml.path),
                    file_path)
      api.git.add([file_path])

    # Copy the HWID database
    if properties.hwid_key:
      api.file.copy('copy HWID database',
                    hwid_repo_path.join('v3/%s' % properties.hwid_key.upper()),
                    dest_hwid_path)
      api.git.add([dest_hwid_path])

    generated_path = dest_repo_path.join('generated')
    api.file.ensure_directory('ensure %s directory exists' % generated_path,
                              generated_path)

    # Mock existence of source path for tests
    api.path.mock_add_paths(SRC_CONFIG)

    # Merge hwid and yaml files with any generated config that we have
    cmd = [cros_config_path.join(JOIN_SCRIPT_PATH), '--output', DST_CONFIG]
    if api.path.exists(SRC_CONFIG):
      cmd += ['--config-bundle', SRC_CONFIG]
    if properties.HasField('public_yaml'):
      cmd += [
          '--public-model',
          public_repo_path.join(properties.public_yaml.path)
      ]
    if properties.HasField('private_yaml'):
      cmd += [
          '--private-model',
          private_repo_path.join(properties.private_yaml.path)
      ]
    if properties.hwid_key:
      cmd += [
          '--hwid',
          '%s/v3/%s' % (hwid_repo_path, properties.hwid_key.upper())
      ]
    if properties.project_name:
      cmd += ['--project-name', properties.project_name]

    # Generate joined output
    api.step("Generate joined configuration", ["vpython"] + cmd)
    api.git.add([DST_CONFIG])

    # Commit changes (if any)
    changed_files = api.git.get_diff_files('HEAD')
    if changed_files:
      commit_msg = \
'''Updating model.yaml and HWID database due to external commit.

This commit was performed automatically by the project_migrator.py recipe.
'''
      dest_ref = 'refs/heads/master'
      api.git_txn.update_ref(properties.dest_repo,
                             dest_ref, lambda: api.git.commit(commit_msg))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': 'https://example.com/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project'
          }))

  yield api.test(
      'no_dest_repo',
      api.properties(
          **{
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': 'https://example.com/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project'
          }), api.expect_exception('ValueError'))

  yield api.test(
      'dest_repo_only',
      api.properties(**{
          'dest_repo': 'https://example.com/some/project/repo',
      }), api.expect_exception('ValueError'))
