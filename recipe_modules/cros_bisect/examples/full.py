# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_bisect',
]

def RunSteps(api):
  api.cros_bisect.set_bisect_builder('wally')
  api.cros_bisect.get_packages()

def GenTests(api):
  yield api.test('basic')

  yield (api.test('with-findit-bisect') +  #
         api.properties(
           findit_bisect={'targets': ['pkg/foo', 'pkg/bar', 'pkg/baz']},
         ))
