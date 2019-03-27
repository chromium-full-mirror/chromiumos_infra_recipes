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
  'expected_packages': Property(kind=List(str)),
}

def RunSteps(api, expected_packages):
  api.cros_bisect.set_bisect_builder('wally')
  api.assertions.assertEqual(api.cros_bisect.get_packages(), expected_packages)

def GenTests(api):
  yield api.test('basic') + api.properties(expected_packages=[])

  yield (api.test('with-findit-bisect') +  #
         api.properties(
           findit_bisect={'targets': ['pkg/foo', 'pkg/bar', 'pkg/baz']},
         ) + #
         api.properties(
           expected_packages=['pkg/foo', 'pkg/bar', 'pkg/baz'],
         ))
