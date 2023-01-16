# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos import common
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
from PB.recipe_modules.chromeos.goma.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'goma',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.goma.initialize(also_bq_upload=True)
  if properties.expected_goma_approach > common.GomaConfig.DEFAULT:
    api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  else:
    api.assertions.assertEqual(api.goma.goma_dir, None)
  api.assertions.assertEqual(
      str(api.goma.default_bqupload_dir), '[CACHE]/goma/bqupload')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  )
          }),
      api.properties(
          TestInputProperties(
              expected_goma_approach=common.GomaConfig.RBE_PROD,
          )),
  )

  yield api.test(
      'basic-no-goma',
      api.properties(
          TestInputProperties(
              expected_goma_approach=common.GomaConfig.DEFAULT,
          )),
  )
