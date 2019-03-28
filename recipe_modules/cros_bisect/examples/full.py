# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_bisect',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

PROPERTIES = {
  # Used to verify the handling of a FindIt invocation and the retrieval
  # of the packages to build.
  'expected_packages': Property(kind=List(str), default=[]),
  # Simulates if the build fails, and cros_bisect is asked to output failure
  # information for FindIt.
  'failed_packages': Property(kind=List(str), default=[]),
}

def RunSteps(api, expected_packages, failed_packages):
  api.cros_bisect.set_bisect_builder('wally')
  api.assertions.assertEqual(api.cros_bisect.get_packages(), expected_packages)

  if failed_packages:
    api.cros_bisect.set_build_compile_failure(failed_packages)

def GenTests(api):
  yield api.test('basic')

  yield (api.test('with-findit-bisect') +  #
         api.properties(
           findit_bisect={'targets': ['pkg/foo', 'pkg/bar', 'pkg/baz']},
         ) + #
         api.properties(
           expected_packages=['pkg/foo', 'pkg/bar', 'pkg/baz'],
         ))

  yield (api.test('with-failed-build') + #
         api.properties(
           failed_packages=['pkg/uno', 'pkg/dos'],
         ))
