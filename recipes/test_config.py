# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Compares Parallel CQ and Legacy cbuildbot configs."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/step',
    'cros_source',
    'gerrit',
    'repo',
]


def RunSteps(api):
  build = api.buildbucket.build
  gerrit_changes = build.input.gerrit_changes

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache()
      if gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      projects = api.repo.project_infos(projects=['chromiumos/chromite'])
      assert len(projects) == 1, 'expected one proto repo, got: %r' % projects
      project = projects[0]

    project_path = api.cros_source.workspace_path.join(project.path)
    with api.context(cwd=project_path):
      api.step(
          'check config drift',
          [project_path.join('config/config_skew_unittest'), '--config_skew'])


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.try_build(),
      api.cq(full_run=True),
  )
