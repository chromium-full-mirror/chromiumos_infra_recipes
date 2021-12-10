# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'cros_resultdb',
]


def RunSteps(api):
  test_args = 'resultdb_settings=%s' % base64.b64encode(
      api.json.dumps({
          'result_format': 'tast',
          'result_file': './path/to/results.json'
      }))
  config = api.cros_resultdb.extract_resultdb_settings(test_args)
  api.cros_resultdb.upload(config)

  bad_test_args = 'not_resultdb_settings=%s' % base64.b64encode(
      api.json.dumps({
          'result_format': 'tast',
      }))
  api.assertions.assertRaises(ValueError,
                              api.cros_resultdb.extract_resultdb_settings,
                              bad_test_args)


def GenTests(api):

  yield api.test('basic', api.buildbucket.ci_build())
