# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

from PB.chromite.api import build_api_test
from PB.chromite.api.artifacts import BundleRequest
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  # Check dumb build API call works.
  input_proto = build_api_test.TestRequestMessage(id='MYD')
  output_type = build_api_test.TestResultMessage.DESCRIPTOR
  output_proto = api.cros_build_api(
      'chromite.api.TestApiService/InputOutputMethod', input_proto, output_type,
      test_output_data='{"result": "good"}')
  api.assertions.assertEqual(output_proto.result, 'good')

  # Check stubs work.
  input_proto = BundleRequest(build_target=BuildTarget(name='target'))
  output_proto = api.cros_build_api.ArtifactsService.BundleFirmware(input_proto)
  api.assertions.assertTrue(
      output_proto.artifacts[0].path.endswith('/tmp/artifact.tar.gz'))

  # Check stubs throw error on bad method calls.
  api.assertions.assertRaises(
      KeyError, api.cros_build_api.ArtifactsService.BundleFoo, input_proto)
  api.assertions.assertRaises(
      TypeError, api.cros_build_api.ArtifactsService.BundleFirmware,
      build_api_test.TestRequestMessage())

  # Check the test API.
  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.BadService/Foo')
  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.ArtifactsService/BadMethod')


def GenTests(api):
  yield api.test('basic')
