# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/context', 'recipe_engine/path',
    'recipe_engine/step', 'cros_cache', 'cros_source', 'repo'
]


# cache_path does not exist therefore will raise a step failure
def RunSteps(api):
  api.assertions.assertRaises(api.step.StepFailure,
                              api.cros_cache.package_source, 'test_file.bz2',
                              api.cros_source.cache_path)


def GenTests(api):
  yield api.test('basic')
