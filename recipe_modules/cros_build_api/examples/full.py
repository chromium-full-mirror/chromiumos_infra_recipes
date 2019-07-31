# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

import json

from google.protobuf import empty_pb2

from PB.chromite.api import artifacts
from PB.chromite.api import binhost
from PB.chromite.api import depgraph
from PB.chromite.api import image
from PB.chromite.api import packages
from PB.chromite.api import sdk
from PB.chromite.api import sysroot
from PB.chromite.api import test
from PB.chromite.api import build_api_test
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  # Check dumb build API call works.
  input_proto = build_api_test.TestRequestMessage(id='MYD')
  output_type = build_api_test.TestResultMessage.DESCRIPTOR
  output_proto = api.cros_build_api(
      'chromite.api.TestApiService/InputOutputMethod', input_proto, output_type,
      test_output_data='{"result": "good"}')
  api.assertions.assertEqual(output_proto.result, 'good')

  # Check ignores unknown fields.
  unknown_field = "ye_unknown_field"
  api.assertions.assertTrue(
      unknown_field not in
      [f.name for f in build_api_test.TestResultMessage.DESCRIPTOR.fields])
  output_proto = api.cros_build_api(
      'chromite.api.TestApiService/InputOutputMethod', input_proto, output_type,
      test_output_data='{"result": "good", "%s": "foobar"}' % unknown_field)

  # Check stubs work.
  input_proto = artifacts.BundleRequest(build_target=BuildTarget(name='target'))
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
  response_type_by_service = {
      'ArtifactsService': {
          endpoint: artifacts.BundleResponse for endpoint in [
              'BundleImageZip', 'BundleTestUpdatePayloads',
              'BundleAutotestFiles', 'BundleTastFiles',
              'BundlePinnedGuestImages', 'BundleFirmware', 'BundleEbuildLogs'
          ]
      },
      'BinhostService': {
          'PrepareBinhostUploads': binhost.PrepareBinhostUploadsResponse,
          'SetBinhost': binhost.SetBinhostResponse,
          'Get' : binhost.BinhostGetResponse,
          'GetPrivatePrebuiltAclArgs': binhost.AclArgsResponse,
      },
      'DependencyService': {
          'GetBuildDependencyGraph': depgraph.GetBuildDependencyGraphResponse,
      },
      'ImageService': {
          'Create': image.CreateImageResult,
          'Test': image.TestImageResult,
      },
      'PackageService': {
          'GetBestVisible': packages.GetBestVisibleResponse,
          'Uprev': packages.UprevPackagesResponse,
      },
      'SdkService': {
          'Create': sdk.CreateResponse,
          'Update': sdk.UpdateResponse,
      },
      'SysrootService': {
          'Create': sysroot.SysrootCreateResponse,
          'InstallToolchain': sysroot.InstallToolchainResponse,
          'InstallPackages': sysroot.InstallPackagesResponse,
      },
      'TestService': {
          'BuildTargetUnitTest': test.BuildTargetUnitTestResponse,
          'ChromiteUnitTest': empty_pb2.Empty,
          'DebugInfoTest': empty_pb2.Empty,
          'VmTest': empty_pb2.Empty,
          'MoblabVmTest': empty_pb2.Empty,
      }
  }
  responses_by_service = api.cros_build_api.test_api.responses_by_service
  for service, responses_by_method in responses_by_service.iteritems():
    for method, response_json in responses_by_method.iteritems():
      api.assertions.assertIn(service, response_type_by_service)
      api.assertions.assertIn(method, response_type_by_service[service])

      # Check we can create a valid response proto.
      response_type = response_type_by_service[service][method]
      response_proto = response_type(**json.loads(response_json))

  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.BadService/Foo')
  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.ArtifactsService/BadMethod')


def GenTests(api):
  yield api.test('basic')
