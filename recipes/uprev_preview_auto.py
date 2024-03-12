# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""ARC++ CTS preview uprev builders.

The builder checkout chromeos branch and run uprev_preview.py to change bundle_url_config.json,
then run generate_controlfiles.py to generate updated controlfiles.

"""
from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

from PB.recipe_engine.result import RawResult
from PB.recipes.chromeos.uprev_preview import UprevPreviewProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_infra_config',
    'cros_source',
    'gerrit',
    'git',
    'repo',
]

PROPERTIES = UprevPreviewProperties

# Projects that need to be synced to input manifest.
_SYNC_PROJECTS = [
    'src/third_party/autotest/files',
    'src/third_party/autotest-tests-cheets',
]

_DEP_EXECUTABLES = [
    [
        'aapt2',
        'gs://chromeos-arc-images/builds/git_udc_release-static_sdk_tools/9594652/aapt2'
    ],
    [
        'aapt',
        'gs://chromeos-arc-images/builds/git_nyc-mr1-arc-linux-static_sdk_tools/3544738/aapt'
    ], ['adb', 'gs://chromeos-arc-images/builds/aosp-sdk-release/7110759/adb']
]

_ANDROID_MAJOR_VERSIONS = ['T']


def RunSteps(api: RecipeApi, properties: UprevPreviewProperties) -> RawResult:
  with api.build_menu.configure_builder():
    return DoRunSteps(api, properties)


def DoRunSteps(api: RecipeApi, properties: UprevPreviewProperties) -> None:
  api.cros_source.ensure_synced_cache(
      projects=_SYNC_PROJECTS, is_staging=api.cros_infra_config.is_staging)

  # Create a branch in the overlay project and sync to ToT.
  overlay_path = api.cros_source.workspace_path.join(
      'src/third_party/autotest/files')
  with api.step.nest('create branch and sync overlay') as pres, \
      api.context(cwd=overlay_path):
    info = api.repo.project_info(project=overlay_path)
    api.git.checkout('HEAD', branch='test-auto')
    api.git.set_upstream(info.remote, info.branch_name)
    api.git.fetch(info.remote)
    api.git.rebase()
    pres.step_text = '{} synced to {}'.format(info.path, api.git.head_commit())

  env_path = api.path.mkdtemp()
  with api.step.nest('set up adb and aapt env'), api.context(
      cwd=api.cros_source.workspace_path):
    for dep_name, dep_url in _DEP_EXECUTABLES:
      api.step(f'download {dep_name}',
               ['gsutil', 'cp', dep_url, f'{env_path}/{dep_name}'])
      api.step(f'chmod {dep_name}', ['chmod', '+x', f'{env_path}/{dep_name}'])

  for android_major_version in _ANDROID_MAJOR_VERSIONS:
    config_path = overlay_path.join(
        f'server/site_tests/cheets_CTS_{android_major_version}')
    modified_files = ''
    current_preview_version = ''
    with api.context(cwd=config_path, env_prefixes={'PATH': [env_path]}):
      api.step('run uprev preview',
               ['/usr/bin/env', 'python3', './uprev_preview.py', '--to_latest'])
      modified_files = api.git.get_working_dir_diff_files()

      load_dict = api.file.read_json('read preview version',
                                     config_path.join('bundle_url_config.json'))
      current_preview_version = load_dict['preview_version_name']

    if modified_files:
      with api.step.nest('commit and generate CL'):
        commit_lines = [
            'cheets_CTS_{}: Uprev to {}.'.format(android_major_version,
                                                 current_preview_version),
            '',
            'BUG=None',
            'TEST={}'.format(api.buildbucket.build_url()),
            '',
        ]
        commit_message = '\n'.join(commit_lines) + '\n'
        with api.context(cwd=overlay_path):
          api.git.add(list(modified_files))
          api.git.commit(commit_message)

        # Create a CL, and submit if needed.
        change = api.gerrit.create_change(
            info.path, reviewers=['ruki@google.com', 'shaochuan@chromium.org'],
            hashtags=[])


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def config_read_preview_step_data(api):
    return api.step_data(
        'read preview version',
        api.file.read_json({
            'public_base': 'https://dl.google.com/dl/android/cts/',
            'partner_base': 'gs://chromeos-partner-gts/',
            'internal_base': 'gs://chromeos-arc-images/cts/bundle/T/',
            'official_url_pattern': 'android-cts-%s-linux_x86-%s.zip',
            'preview_url_pattern': 'android-cts-%s-linux_x86-%s.zip',
            'official_version_name': '13_r7',
            'preview_version_name': '11777022',
            'abi_list': {
                'arm': 'test_suites_arm64',
                'x86': 'test_suites_x86_64'
            }
        }),
    )

  yield api.build_menu.test(
      'basic', config_read_preview_step_data(api),
      api.post_check(post_process.MustRun, 'create branch and sync overlay'),
      api.post_check(post_process.MustRun, 'set up adb and aapt env'),
      api.post_check(post_process.MustRun, 'run uprev preview'),
      api.post_check(post_process.MustRun, 'read preview version'))

  yield api.build_menu.test(
      'generate_gerrit_cl', config_read_preview_step_data(api),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'create branch and sync overlay'),
      api.post_check(post_process.MustRun, 'set up adb and aapt env'),
      api.post_check(post_process.MustRun, 'run uprev preview'),
      api.post_check(post_process.MustRun, 'read preview version'),
      api.post_check(post_process.MustRun, 'commit and generate CL'))
