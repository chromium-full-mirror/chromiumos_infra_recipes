# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure
from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'repo',
]



def RunSteps(api):
  # clean report_manifest_branch_state
  test_data = api.properties.get('test_data')
  stdout = api.repo.report_manifest_branch_state(projects=['foo'],
                                                 test_data=test_data)
  api.assertions.assertEqual(stdout, test_data)

  # step failure in report_manifest_branch_state
  with api.assertions.assertRaisesRegexp(StepFailure,
                                         'tested failure in repo-info step'):
    api.repo.report_manifest_branch_state(test_failure=True)


def GenTests(api):
  yield api.test('basic', api.properties(test_data='Repo info test'),
                 api.post_process(DropExpectation))
