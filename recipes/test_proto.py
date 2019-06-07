# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies the proto repository."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/step',
    'cros_source',
    'git',
    'gerrit',
    'repo',
]


def RunSteps(api):
  build = api.buildbucket.build
  gerrit_changes = build.input.gerrit_changes

  # TODO(crbug.com/972258): Stop doing full checkout.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      if gerrit_changes:
        gerrit_changes = api.cq.ordered_gerrit_changes
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      projects = api.repo.project_infos(projects=['chromiumos/infra/proto'])
      assert len(projects) == 1, 'expected one proto repo, got: %r' % projects
      project = projects[0]

    project_path = api.cros_source.workspace_path.join(project.path)
    with api.context(cwd=project_path):
      api.step('check protos compile', ['sh', project_path.join('generate.sh')])

      with api.step.nest('check gen files committed'):
        diff_files = api.git.get_working_dir_diff_files()
        if diff_files:
          raise api.step.StepFailure(
              'Uh oh! Running generate.sh produced files not included in your '
              'change(s). Please run the script, amend your commit, and try '
              'again. Missing generated files were: {}'.format(
                  ', '.join(diff_files)))

def GenTests(api):
  yield (api.test('with-gerrit-changes') +  #
         api.buildbucket.try_build() +  #
         api.cq(full_run=True))
