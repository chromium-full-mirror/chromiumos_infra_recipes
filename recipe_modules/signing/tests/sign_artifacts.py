# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for sign_artifacts."""

from google.protobuf.json_format import MessageToDict

from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  api.signing.sign_artifacts()


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/signing':
              MessageToDict(SigningProperties(local_signing=True))
      }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test('failure', api.post_process(post_process.DropExpectation),
                 api.expect_exception('Exception'), status='INFRA_FAILURE')
