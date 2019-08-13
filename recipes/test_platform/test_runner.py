# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""

from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step'
]

PROPERTIES = TestRunnerProperties

def validate_request(api, properties):
  """Validate the CrosTfeProperties.

  Args:
    * api (object): See RunSteps documentation.
    * properties (TestRunnerProperties): The input request.

  Raises: An exception if there are invalid properties.
  """
  with api.step.nest('validate request'):
    if not properties.request.test.autotest.name:
      raise ValueError("Test name must be specified")

def RunSteps(api, properties):
  validate_request(api, properties)
  # TODO(crbug/974054): Implement this.

def GenTests(api):
  yield (api.test('basic') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})))

  yield (api.test('test_name_missing') + #
         api.properties(TestRunnerProperties(request={'test': {}})) + #
         api.expect_exception('ValueError'))
