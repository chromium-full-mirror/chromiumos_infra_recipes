# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.crostfe import CrosTfeProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step'
]

PROPERTIES = CrosTfeProperties

def validate_request(api, properties):
  """Validate the CrosTfeProperties.

  Args:
    * api (object): See RunSteps documentation.
    * properties (CrosTfeProperties): The input request.

  Raises: An exception if there are invalid properties.
  """
  with api.step.nest('validate request'):
    if not properties.params.board:
      raise ValueError("params.board must be specified")

def RunSteps(api, properties):
  validate_request(api, properties)

def GenTests(api):
  yield (api.test('basic') + #
         api.properties(CrosTfeProperties(params={'board': 'test_board'})))

  yield (api.test('board_param_missing') + #
         api.properties(CrosTfeProperties(params={'board': ''})) + #
         api.expect_exception('ValueError'))