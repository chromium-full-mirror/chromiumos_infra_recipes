# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import six

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'cros_resultdb',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  test_args = 'resultdb_settings=%s' % six.ensure_str(
      base64.b64encode(
          six.ensure_binary(
              api.json.dumps({
                  'base_tags': ['test_suite:fake-suite'],
                  'result_format': 'tast',
                  'result_file': './path/to/results.json'
              }))))
  config = api.cros_resultdb.extract_chromium_resultdb_settings(test_args)
  api.cros_resultdb.upload(config)

  bad_test_args = 'not_resultdb_settings=%s' % six.ensure_str(
      base64.b64encode(
          six.ensure_binary(api.json.dumps({
              'result_format': 'tast',
          }))))
  api.assertions.assertRaises(
      ValueError, api.cros_resultdb.extract_chromium_resultdb_settings,
      bad_test_args)


def GenTests(api):

  yield api.test('basic', api.buildbucket.ci_build())
