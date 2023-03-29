# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'cros_resultdb',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  test_args = api.cros_resultdb.test_api.resultdb_settings_arg({
      'result_format': 'tast',
      'result_file': './path/to/results.json'
  })
  config = api.cros_resultdb.extract_chromium_resultdb_settings(test_args)
  api.cros_resultdb.upload(config, 'http://localhost/stainless/url',
                           'http://localhost/testhaus/url')


def GenTests(api):
  yield api.test('basic', api.buildbucket.ci_build())
