# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'autotest_status_parser',
]

from PB.recipe_modules.chromeos.autotest_status_parser.autotest_status_parser \
  import AutotestStatusParserProperties
from PB.test_platform.skylab_test_runner.result import Result

def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.autotest_status_parser.parse("")

  result = api.autotest_status_parser.parse("/path/to/results")


def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(
             **{'$chromeos/autotest_status_parser':
                 AutotestStatusParserProperties(
                     version=AutotestStatusParserProperties.Version(
                         cipd_label='some-cipd-label',
        ))}))