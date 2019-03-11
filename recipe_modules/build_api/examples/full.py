# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'build_api',
]

from PB.chromite.api import build_api_test as build_api_test_pb2


def RunSteps(api):
  api.build_api.call_json('chromite.api.Service/Method', {})

  input = build_api_test_pb2.TestRequestMessage()
  input.id = 'MYD'
  output = api.build_api.call_proto(
      'chromite.api.TestApiService/InputOutputMethod', input,
      test_output_data='{"result": "good"}')
  api.assertions.assertEqual(output.result, 'good')

  api.assertions.assertRaises(KeyError, api.build_api.call_proto,
                              'bad.package.Service/Method', input)

  api.assertions.assertRaises(TypeError, api.build_api.call_proto,
                              'chromite.api.TestApiService/InputOutputMethod',
                              build_api_test_pb2.TestResultMessage())


def GenTests(api):
  yield api.test('basic')
