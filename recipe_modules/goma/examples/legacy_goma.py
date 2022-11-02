# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'goma',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.goma.initialize(also_bq_upload=True)
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  api.assertions.assertEqual(
      str(api.goma.default_bqupload_dir), '[CACHE]/goma/bqupload')


def GenTests(api):
  yield api.test('basic',)
