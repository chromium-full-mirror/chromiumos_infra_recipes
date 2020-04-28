# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]

import json

from google.protobuf import empty_pb2

from PB.chromite.api import api as meta_api
from PB.chromite.api import artifacts
from PB.chromite.api import binhost
from PB.chromite.api import depgraph
from PB.chromite.api import image
from PB.chromite.api import packages
from PB.chromite.api import sdk
from PB.chromite.api import sysroot
from PB.chromite.api import test
from PB.chromite.api import toolchain
from PB.chromite.api import build_api_test
from PB.chromiumos.common import BuildTarget

from PB.recipe_modules.chromeos.analysis_service.analysis_service import (
    AnalysisServiceProperties)
from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import (
    CrosBuildApiProperties)

def RunSteps(api):
  # Check dumb build API call works. Use protos defined in
  # chromiumos_infra_proto/src/analysis_service/analysis_service.proto so that
  # the analysis_service will write an event for the result.
  input_proto = binhost.PrepareBinhostUploadsRequest(
      build_target=BuildTarget(name='target'))
  output_type = binhost.PrepareBinhostUploadsResponse.DESCRIPTOR
  output_proto = api.cros_build_api(
      'chromite.api.BinhostService/PrepareBinhostsUploads', input_proto,
      output_type, test_output_data='{"uploads_dir": "/binhosts/path"}',
      test_teelog_data='Logfile contents for build_cmd.')
  api.assertions.assertEqual(output_proto.uploads_dir, '/binhosts/path')

  # Check ignores unknown fields.
  unknown_field = 'ye_unknown_field'
  api.assertions.assertNotIn(
      unknown_field,
      [f.name for f in build_api_test.TestResultMessage.DESCRIPTOR.fields])
  output_proto = api.cros_build_api(
      'chromite.api.TestApiService/InputOutputMethod', input_proto, output_type,
      test_output_data='{"result": "good", "%s": "foobar"}' % unknown_field,
      test_teelog_data='Logfile contents for failing case of build_cmd.')

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

  api.assertions.assertEqual((1, 1, 0), api.cros_build_api.version)

  # Check the test API.
  response_type_by_service = {
      'ArtifactsService': {
          'FetchPinnedGuestImageUris': artifacts.PinnedGuestImageUriResponse,
          # As of 1.1.0, the following ArtifactsService endpoints are
          # deprecated.
          'BundleImageZip': artifacts.BundleResponse,
          'BundleTestUpdatePayloads': artifacts.BundleResponse,
          'BundleAutotestFiles': artifacts.BundleResponse,
          'BundleTastFiles': artifacts.BundleResponse,
          'BundlePinnedGuestImages': artifacts.BundleResponse,
          'BundleFirmware': artifacts.BundleResponse,
          'BundleEbuildLogs': artifacts.BundleResponse,
          'BundleChromeOSConfig': artifacts.BundleResponse,
          'ExportCpeReport': artifacts.BundleResponse,
          'BundleImageArchives': artifacts.BundleResponse,
      },
      'BinhostService': {
          'PrepareBinhostUploads': binhost.PrepareBinhostUploadsResponse,
          'SetBinhost': binhost.SetBinhostResponse,
          'Get': binhost.BinhostGetResponse,
          'GetPrivatePrebuiltAclArgs': binhost.AclArgsResponse,
          'RegenBuildCache': binhost.RegenBuildCacheResponse,
      },
      'DependencyService': {
          'GetBuildDependencyGraph': depgraph.GetBuildDependencyGraphResponse,
          'GetToolchainPaths': depgraph.GetToolchainPathsResponse,
      },
      'ImageService': {
          'Create': image.CreateImageResult,
          'Test': image.TestImageResult,
      },
      'MethodService': {
          'Get': meta_api.MethodGetResponse,
      },
      'PackageService': {
          'BuildsChrome': packages.BuildsChromeResponse,
          'GetBestVisible': packages.GetBestVisibleResponse,
          'GetChromeVersion': packages.GetChromeVersionResponse,
          'GetTargetVersions': packages.GetTargetVersionsResponse,
          'HasChromePrebuilt': packages.HasChromePrebuiltResponse,
          'HasPrebuilt': packages.HasPrebuiltResponse,
          'Uprev': packages.UprevPackagesResponse,
          'UprevVersionedPackage': packages.UprevVersionedPackageResponse,
      },
      'SdkService': {
          'Clean': sdk.CleanResponse,
          'Create': sdk.CreateResponse,
          'Delete': sdk.UpdateResponse,
          'Unmount': sdk.UnmountResponse,
          'Update': sdk.UpdateResponse,
          'CreateSnapshot': sdk.CreateSnapshotResponse,
          'RestoreSnapshot': sdk.RestoreSnapshotResponse,
      },
      'SysrootService': {
          'Create': sysroot.SysrootCreateResponse,
          'InstallToolchain': sysroot.InstallToolchainResponse,
          'InstallPackages': sysroot.InstallPackagesResponse,
      },
      'TestService': {
          'BuildTargetUnitTest': test.BuildTargetUnitTestResponse,
          'ChromitePytest': empty_pb2.Empty,
          'ChromiteUnitTest': empty_pb2.Empty,
          'DebugInfoTest': empty_pb2.Empty,
          'VmTest': empty_pb2.Empty,
          'MoblabVmTest': empty_pb2.Empty,
      },
      'ToolchainService': {
          'PrepareForBuild': toolchain.PrepareForToolchainBuildResponse,
          'BundleArtifacts': toolchain.BundleToolchainResponse,
      },
      'VersionService': {
          'Get': meta_api.VersionGetResponse,
      },
  }
  # If needed, add the endpoints introduced in API verison 1.1.0.
  if api.cros_build_api.version >= (1, 1, 0):
    response_type_by_service['ArtifactsService'].update({
        'PrepareForBuild': artifacts.PrepareForBuildResponse,
        'BundleArtifacts': artifacts.BundleArtifactsResponse,
    })

  responses_by_service = api.cros_build_api.test_api.responses_by_service()
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
  yield (api.test('basic'))

  yield (api.test('basic_with_output') +  #
         api.properties(**{
             # This property is needed to capture tee_log output of build_api.
             '$chromeos/cros_build_api':
             CrosBuildApiProperties(capture_stdout_stderr=True),
             # This property is needed to attach build api output to event.
             '$chromeos/analysis_service':
             AnalysisServiceProperties(max_stdout_stderr_bytes=64)
         })
  )
