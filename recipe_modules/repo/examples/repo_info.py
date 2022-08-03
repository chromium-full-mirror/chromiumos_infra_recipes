# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  test_data = api.properties.get('test_data')
  stdout = api.repo.report_manifest_branch_state(test_data)
  api.assertions.assertEqual(stdout, test_data)


def GenTests(api):
  yield api.test('basic') + api.properties(test_data='Repo info test')
