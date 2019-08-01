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

from PB.chromiumos.common import PackageInfo

from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.recipe_modules.chromeos.cros_bisect.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties

def RunSteps(api, properties):
  api.cros_bisect.set_bisect_builder('wally')
  api.cros_bisect.set_orchestrator_bisect_builder()
  api.assertions.assertItemsEqual(api.cros_bisect.get_packages(),
                                  properties.expected_packages)

  api.cros_bisect.set_compile_failures(properties.failed_packages)

def GenTests(api):
  yield api.test('basic')

  yield (api.test('with-findit-bisect') +  #
         api.properties(
             **{'$chromeos/cros_bisect': CrosBisectProperties(targets=[
                 api.cros_bisect.serialized_package_info('foo', 'cat1', '1'),
                 api.cros_bisect.serialized_package_info('bar', 'cat1', '2'),
                 api.cros_bisect.serialized_package_info('baz', 'cat2', '3'),
             ])}
         ) + #
         api.properties(TestInputProperties(expected_packages=[
               PackageInfo(package_name='foo', category='cat1', version='1'),
               PackageInfo(package_name='bar', category='cat1', version='2'),
               PackageInfo(package_name='baz', category='cat2', version='3'),
           ],
         )))

  yield (api.test('with-failed-build') + #
         api.properties(TestInputProperties(failed_packages=[
               PackageInfo(package_name='uno', category='pkg', version='1'),
               PackageInfo(package_name='dos', category='pkg', version='2'),
           ],
         )))
