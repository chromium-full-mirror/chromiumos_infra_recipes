# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.test_platform.request import Request

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'cros_resultdb',
]



def RunSteps(api):
  config = {
      'result_format':
          'tast',
      'result_file':
          './path/to/results.json',
      'visibility_mode':
          Request.Params.ResultsUploadConfig.TestResultsUploadVisibility
          .TEST_RESULTS_VISIBILITY_CUSTOM_REALM,
      'custom_realm':
          'eli'
  }
  api.cros_resultdb.upload(config, 'http://localhost/testhaus/url')


def GenTests(api):
  yield api.test('basic', api.buildbucket.ci_build())
