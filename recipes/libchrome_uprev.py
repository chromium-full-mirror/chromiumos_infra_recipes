# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for upreving libchrome"""

import re

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'build_menu',
    'cros_sdk',
    'cros_source',
    'src_state',
    'git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PUSH_OPTION_LABEL_RE = re.compile(
    r'(Auto-Submit|Verified|Commit-Queue)([+-][12])')


def RunSteps(api: RecipeApi):
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto

  with api.build_menu.configure_builder(missing_ok=True, commit=commit):
    # automated_uprev.py needs chroot to test emerge libchrome.
    with api.build_menu.setup_workspace_and_chroot():
      project_dir = api.cros_source.workspace_path.join(
          'src/platform/libchrome')
      with api.context(cwd=project_dir):
        project_info = api.repo.project_info()
        step_data = api.cros_sdk.run('generate uprev commit', [
            'vpython3',
            '../platform/libchrome/libchrome_tools/developer-tools/uprev/automated_uprev.py',
            '--head',
            '--recipe',
        ], stdout=api.raw_io.output_text())

        push_options = step_data.stdout.strip()

        with api.step.nest('validate push options'):
          if not push_options.startswith('%'):
            raise StepFailure(
                'invalid push options ("{}"): should start with %'.format(
                    push_options))
          for option in push_options[1:].split(','):
            if not option:
              continue
            option = option.split('=')
            if option[0] not in ['r', 'topic', 'l']:
              raise StepFailure(
                  'invalid push option ("{}"): only r(eviewer), topic, l(abel) '
                  'options are allowed'.format(option))
            if option[0] == 'l' and (len(option) < 2 or
                                     not PUSH_OPTION_LABEL_RE.match(option[1])):
              raise StepFailure(
                  'invalid label-type push option ("{}"): '
                  'only Auto-Submit, Verified, Commit-Queue labels with value '
                  'are allowed'.format(option[1]))

        with api.step.nest('push uprev commit'):
          api.git.push(project_info.remote, 'HEAD:refs/for/main' + push_options,
                       dry_run=api.build_menu.is_staging)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'script-success',
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
  )

  yield api.test(
      'script-wrong-option-format',
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              'r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'))

  yield api.test(
      'script-invalid-option',
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%submit,r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'))

  yield api.test(
      'script-invalid-label',
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,'
              'l=Auto-Submit+1,l=Verified+1,l=Code-Review+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'))
