# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'tast_results',
]


def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')
  task_result = api.tast_results.get_results(temp_dir, 'fancy-suite')
  api.tast_results.print_results(task_result, temp_dir)

  failures = api.tast_results.get_failures(task_result)
  api.assertions.assertEqual(len(failures), 1)
  api.assertions.assertEqual(failures[0].kind, 'vm test')
  api.assertions.assertEqual(failures[0].fatal, True)
  api.assertions.assertEqual(failures[0].title, 'arc.Boot')


def GenTests(api):
  yield api.test('basic')
