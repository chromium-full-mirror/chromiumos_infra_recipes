# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]

from PB.recipe_modules.chromeos.cros_infra_config.tests.test import (
    DetermineIfStagingProperties)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = DetermineIfStagingProperties


def RunSteps(api, properties):
  api.cros_infra_config.determine_if_staging()
  api.assertions.assertEqual(api.cros_infra_config.is_staging,
                             properties.expected_is_staging)


def GenTests(api):

  def expected_staging(is_staging):
    return api.properties(
        DetermineIfStagingProperties(expected_is_staging=is_staging))

  yield api.test('staging-bucket', expected_staging(True),
                 api.buildbucket.generic_build(bucket="staging"))

  yield api.test('staging-builder', expected_staging(True),
                 api.buildbucket.generic_build(builder="staging-sign-image"))

  yield api.test('generic-builder', expected_staging(False),
                 api.buildbucket.generic_build())
