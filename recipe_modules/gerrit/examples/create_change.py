# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'gerrit',
]

def RunSteps(api):
  change = api.gerrit.create_change('project', reviewers=['jeff'], topic='pupr')
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'project')
  api.assertions.assertEqual(change.change, 123)

  project_path = api.path['start_dir'].join('bar')
  change = api.gerrit.create_change('bar', project_path=project_path)
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'bar')
  api.assertions.assertEqual(change.change, 456)

  # Try creating a change for a project that does not exist in the checkout
  # (see test data) and ALSO does not have a project_path specified. This should
  # fail.
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
      api.step_data(
          'create gerrit change for foo.check if project foo exists.repo info',
          stderr=api.raw_io.output('project foo not found')),
      api.post_check(post_process.StepFailure, 'create gerrit change for foo'))
