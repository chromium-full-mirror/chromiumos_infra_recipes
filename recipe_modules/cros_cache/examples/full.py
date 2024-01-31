# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'cros_cache',
]



def RunSteps(api):
  cache_dir = api.cros_cache.create_cache_dir('temp_cache')
  api.assertions.assertTrue(api.path.exists(cache_dir))
  api.cros_cache.write_and_upload_version('test-gs-bucket',
                                          'test-version-file.txt',
                                          'initial-recovery-version')


def GenTests(api):
  yield api.test('basic')
