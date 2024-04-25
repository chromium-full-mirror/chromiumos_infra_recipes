# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'gerrit',
    'git_cl',
    'src_state',
]



def RunSteps(api):
  change = api.gerrit.create_change('project', reviewers=['jeff'], topic='pupr')
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'project')
  api.assertions.assertEqual(change.change, 123)

  project_path = api.path.start_dir / 'bar'
  change = api.gerrit.create_change('bar', project_path=project_path)
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'bar')
  api.assertions.assertEqual(change.change, 456)

  change = api.gerrit.create_change('baz', ref='refs/heads/remotebranch')
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'baz')
  api.assertions.assertEqual(change.change, 789)

  # Try creating a change for a project that does not exist in the checkout
  # (see test data) and ALSO does not have a project_path specified. This should
  # fail.
  with api.assertions.assertRaises(StepFailure):
    api.gerrit.create_change('foo')


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.simulated_create_change(
          'create gerrit change for project',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.gerrit.simulated_create_change(
          'create gerrit change for bar',
          'https://host-review.googlesource.com/c/bar/+/456'),
      api.path.exists(api.src_state.workspace_path),
      api.gerrit.simulated_create_change(
          'create gerrit change for baz',
          'https://host-review.googlesource.com/c/baz/+/789'),
      api.path.exists(api.src_state.workspace_path),
      api.step_data(
          'create gerrit change for baz.git branch',
          stdout=api.raw_io.output_text('main\notherbranch\n'),
      ),
      api.git_cl.issues('create gerrit change for baz',
                        {'refs/heads/remotebranch': '123'}),
      api.step_data(
          'create gerrit change for foo.check if project foo exists.repo info',
          stderr=api.raw_io.output_text('project foo not found')),
  )
