# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'cros_resultdb',
]


def RunSteps(api):
  test_args = api.cros_resultdb.test_api.resultdb_settings_arg({
      # 'GPUFamily' and 'GPUVendor' are an invalid tags.
      'base_tags': [
          'test_suite:fake-suite', 'GPUFamily:tigerlake',
          'GPUVendor:' + 'intel' * 100
      ],
      'result_format': 'tast',
      'result_file': './path/to/results.json'
  })
  config = api.cros_resultdb.extract_chromium_resultdb_settings(test_args)
  api.cros_resultdb.upload(config, 'http://localhost/testhaus/url')


def GenTests(api):
  yield api.test('basic', api.buildbucket.ci_build())
