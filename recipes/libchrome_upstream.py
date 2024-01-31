# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating libchrome upstream branch"""

import re

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'build_menu',
    'chrome',
    'cros_source',
    'src_state',
    'gcloud',
    'git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'repo',
]

CHROMIUM_OBJECTS_CACHE = 'chrome_cache/chromium.googlesource.com-chromium-src/objects'


def RunSteps(api: RecipeApi):
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto

  with api.build_menu.configure_builder(disable_sdk=True, missing_ok=True,
                                        commit=commit):
    with api.build_menu.setup_workspace():
      project_dir = api.cros_source.workspace_path.join(
          'src/platform/libchrome')
      with api.context(cwd=project_dir):
        project_info = api.repo.project_info()
        with api.step.nest('fetch latest chromium'):
          with api.step.nest('use chromium cache'):
            chrome_cache_dir = api.path.mkdtemp()
            api.chrome.cache_sync(cache_path=chrome_cache_dir, sync=False,
                                  step_name='populate cached chrome')
            chrome_cache_objects_dir = chrome_cache_dir.join(
                CHROMIUM_OBJECTS_CACHE)
            git_objects_info_dir = project_dir.join('.git/objects/info')
            api.file.ensure_directory('ensure .git/objects/info',
                                      git_objects_info_dir)
            api.file.write_text('create chrome git reference',
                                git_objects_info_dir.join('alternates'),
                                str(chrome_cache_objects_dir))
          api.step('git fetch chromium', [
              '/usr/bin/git', 'fetch',
              'https://chromium.googlesource.com/chromium/src'
          ])
          chromium_head = api.step(
              'get chromium head', ['/usr/bin/git', 'rev-parse', 'FETCH_HEAD'],
              stdout=api.raw_io.output_text()).stdout.strip()
        with api.step.nest('sync upstream branch'):
          upstream_branch_head = api.git.fetch_ref(project_info.remote,
                                                   'refs/heads/upstream')
        with api.step.nest('generate new upstream branch locally'):
          # Just print libchrome HEAD so we know which version of
          # libchrome_tools is used.
          api.git.head_commit()
          step_data = api.step('generate new upstream head', [
              'vpython3',
              'libchrome_tools/developer-tools/uprev/update_upstream.py',
              upstream_branch_head, chromium_head, '--all'
          ], stdout=api.raw_io.output_text())
          result_commit = step_data.stdout.strip()
          if not (result_commit and re.match(r'^[0-9a-f]{40}$', result_commit)):
            raise StepFailure('Got invalid commit %s' % result_commit)
          api.git.log(upstream_branch_head, result_commit)
        # Pushes to upstream branch, instead of tip-of-tree.
        # The script should run the script from libchrome tip-of-tree to generate
        # updated upstream (based on inputs from Chromium tip-of-tree)
        api.git.push(project_info.remote,
                     '%s:refs/heads/upstream' % (result_commit),
                     dry_run=api.build_menu.is_staging)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'script-success',
      api.step_data(
          'generate new upstream branch locally.generate new upstream head',
          stdout=api.raw_io.output_text(
              '49d1e4a4a6ca65114208c498416be3b85e10cc8e\n')),
      api.step_data(
          'fetch latest chromium.get chromium head',
          stdout=api.raw_io.output_text(
              'cb10da20a312790d1d2421ae2f8dc2ea831cffa3\n')))

  yield api.test(
      'script-unexpected',
      api.step_data(
          'generate new upstream branch locally.generate new upstream head',
          stdout=api.raw_io.output_text('Unexpected Result')),
      api.step_data(
          'fetch latest chromium.get chromium head',
          stdout=api.raw_io.output_text(
              'cb10da20a312790d1d2421ae2f8dc2ea831cffa3\n')),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
