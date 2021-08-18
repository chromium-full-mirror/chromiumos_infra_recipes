# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'goma',
]


def RunSteps(api):
  api.goma.initialize(also_bq_upload=True)
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  api.assertions.assertEqual(
      str(api.goma.default_bqupload_dir), '[CACHE]/goma/bqupload')


def GenTests(api):
  yield api.test('basic',)
