# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating libchrome upstream branch"""

import re

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'build_menu',
    'cros_source',
    'src_state',
    'git',
    'recipe_engine/context',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'repo',
]


def RunSteps(api):
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto

  with api.build_menu.configure_builder(disable_sdk=True, missing_ok=True,
                                        commit=commit):
    with api.build_menu.setup_workspace():
      project_dir = api.cros_source.workspace_path.join(
          'src/aosp/external/libchrome')
      with api.context(cwd=project_dir):
        project_info = api.repo.project_info()
        with api.step.nest('generate new upstream branch locally'):
          chromium_heads = api.git.fetch_ref(
              'https://chromium.googlesource.com/chromium/src',
              'refs/heads/main')
          step_data = api.step(
              'generate new upstream head',
              [
                  'vpython3',
                  'libchrome_tools/developer-tools/uprev/update_upstream.py',
                  'cros/upstream',
                  chromium_heads,
                  # TODO(b/180558819): use --all to support picking old
                  # history of new files after filter change.
                  '--forward'
              ],
              stdout=api.raw_io.output())
          result_commit = step_data.stdout.strip()
          if not (result_commit and re.match(r'^[0-9a-f]{40}$', result_commit)):
            raise StepFailure('Got invalid commit %s' % result_commit)
          api.git.log('cros/upstream', result_commit)
        # Pushes to upstream branch, instead of tip-of-tree.
        # The script should run the script from libchrome tip-of-tree to generate
        # updated upstream (based on inputs from Chromium tip-of-tree)
        api.git.push(project_info.remote,
                     '%s:refs/heads/upstream' % (result_commit),
                     dry_run=api.build_menu.is_staging)


def GenTests(api):
  yield api.test(
      'script success',
      api.step_data(
          'generate new upstream branch locally.generate new upstream head',
          stdout=api.raw_io.output(
              '49d1e4a4a6ca65114208c498416be3b85e10cc8e\n')))

  yield api.test(
      'script unexpected',
      api.step_data(
          'generate new upstream branch locally.generate new upstream head',
          stdout=api.raw_io.output('Unexpected Result')))
