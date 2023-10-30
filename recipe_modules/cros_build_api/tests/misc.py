# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from google.protobuf import empty_pb2

from PB.chromite.api import android
from PB.chromite.api import api as meta_api
from PB.chromite.api import artifacts
from PB.chromite.api import binhost
from PB.chromite.api import build_api_test
from PB.chromite.api import copybot
from PB.chromite.api import depgraph
from PB.chromite.api import dlc
from PB.chromite.api import firmware
from PB.chromite.api import image
from PB.chromite.api import observability
from PB.chromite.api import packages
from PB.chromite.api import payload
from PB.chromite.api import portage_explorer
from PB.chromite.api import sdk
from PB.chromite.api import sdk_subtools
from PB.chromite.api import sysroot
from PB.chromite.api import test
from PB.chromite.api import toolchain
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import CrosBuildApiProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  _ = api.cros_build_api.log_level
  input_proto = binhost.PrepareBinhostUploadsRequest(
      build_target=BuildTarget(name='target'))
  output_type = binhost.PrepareBinhostUploadsResponse.DESCRIPTOR

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
  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.ArtifactsService.BundleFoo,
                              input_proto)
  api.assertions.assertRaises(
      TypeError, api.cros_build_api.ArtifactsService.BundleFirmware,
      build_api_test.TestRequestMessage())

  # Verify that the API is new enough for us.
  api.assertions.assertTrue(api.cros_build_api.is_at_least_version(1, 1, 0))

  # Check the test API.
  response_type_by_service = {
      'AndroidService': {
          'GetLatestBuild': android.GetLatestBuildResponse,
          'MarkStable': android.MarkStableResponse,
          'WriteLKGB': android.WriteLKGBResponse,
      },
      'ApiService': {
          'CompileProto': meta_api.CompileProtoResponse,
      },
      'ArtifactsService': {
          'FetchMetadata': artifacts.FetchMetadataResponse,
          'FetchPinnedGuestImageUris': artifacts.PinnedGuestImageUriResponse,
          'BuildSetup': artifacts.BuildSetupResponse,
          'Get': artifacts.GetResponse,
          # TODO(crbug/1034529): All of the following are migrating to Get.
          'BundleDebugSymbols': artifacts.BundleResponse,
          'BundleImageZip': artifacts.BundleResponse,
          'BundleTestUpdatePayloads': artifacts.BundleResponse,
          'BundleAutotestFiles': artifacts.BundleResponse,
          'BundleTastFiles': artifacts.BundleResponse,
          'BundlePinnedGuestImages': artifacts.BundleResponse,
          'BundleFirmware': artifacts.BundleResponse,
          'BundleEbuildLogs': artifacts.BundleResponse,
          'BundleChromeOSConfig': artifacts.BundleResponse,
          'BundleImageArchives': artifacts.BundleResponse,
          'BundleFpmcuUnittests': artifacts.BundleResponse,
          'BundleGceTarball': artifacts.BundleResponse,
      },
      'BinhostService': {
          'PrepareBinhostUploads':
              binhost.PrepareBinhostUploadsResponse,
          'PrepareDevInstallBinhostUploads':
              binhost.PrepareDevInstallBinhostUploadsResponse,
          'PrepareChromeBinhostUploads':
              binhost.PrepareChromeBinhostUploadsResponse,
          'SetBinhost':
              binhost.SetBinhostResponse,
          'Get':
              binhost.BinhostGetResponse,
          'GetPrivatePrebuiltAclArgs':
              binhost.AclArgsResponse,
          'RegenBuildCache':
              binhost.RegenBuildCacheResponse,
          'GetBinhostConfPath':
              binhost.GetBinhostConfPathResponse,
      },
      'CopybotService': {
          'RunCopybot': copybot.RunCopybotResponse,
      },
      'DependencyService': {
          'GetBuildDependencyGraph': depgraph.GetBuildDependencyGraphResponse,
          'GetToolchainPaths': depgraph.GetToolchainPathsResponse,
          'List': depgraph.ListResponse,
      },
      'DlcService': {
          'GenerateDlcArtifactsList': dlc.GenerateDlcArtifactsListResponse,
      },
      'FirmwareService': {
          'BuildAllFirmware': firmware.BuildAllFirmwareResponse,
          'TestAllFirmware': firmware.TestAllFirmwareResponse,
          'BundleFirmwareArtifacts': firmware.BundleFirmwareArtifactsResponse,
      },
      'ImageService': {
          'Create': image.CreateImageResult,
          'CreateNetboot': image.CreateNetbootResponse,
          'PushImage': image.PushImageResponse,
          'SignImage': image.SignImageResponse,
          'Test': image.TestImageResult,
      },
      'MethodService': {
          'Get': meta_api.MethodGetResponse,
      },
      'ObservabilityService': {
          'GetImageSizeData': observability.GetImageSizeDataResponse,
      },
      'PackageService': {
          'BuildsChrome': packages.BuildsChromeResponse,
          'GetAndroidMetadata': packages.GetAndroidMetadataResponse,
          'GetBuilderMetadata': packages.GetBuilderMetadataResponse,
          'GetBestVisible': packages.GetBestVisibleResponse,
          'GetChromeVersion': packages.GetChromeVersionResponse,
          'GetTargetVersions': packages.GetTargetVersionsResponse,
          'HasChromePrebuilt': packages.HasChromePrebuiltResponse,
          'HasPrebuilt': packages.HasPrebuiltResponse,
          'NeedsChromeSource': packages.NeedsChromeSourceResponse,
          'Uprev': packages.UprevPackagesResponse,
          'UprevVersionedPackage': packages.UprevVersionedPackageResponse,
          'RevBumpChrome': packages.UprevVersionedPackageResponse,
      },
      'PayloadService': {
          'GeneratePayload': payload.GenerationResponse,
      },
      'PortageExplorerService': {
          'RunSpiders': portage_explorer.RunSpidersResponse,
      },
      'SdkService': {
          'Clean': sdk.CleanResponse,
          'Create': sdk.CreateResponse,
          'BuildPrebuilts': sdk.BuildPrebuiltsResponse,
          'BuildSdkTarball': sdk.BuildSdkTarballResponse,
          'CreateManifestFromSdk': sdk.CreateManifestFromSdkResponse,
          'BuildSdkToolchain': sdk.BuildSdkToolchainResponse,
          'Delete': sdk.UpdateResponse,
          'Unmount': sdk.UnmountResponse,
          'Update': sdk.UpdateResponse,
          'Uprev': sdk.UprevResponse,
          'CreateBinhostCLs': sdk.CreateBinhostCLsResponse,
          'UploadPrebuiltPackages': sdk.UploadPrebuiltPackagesResponse,
      },
      'SdkSubtoolsService': {
          'BuildSdkSubtools': sdk_subtools.BuildSdkSubtoolsResponse,
          'UploadSdkSubtools': sdk_subtools.UploadSdkSubtoolsResponse,
      },
      'SysrootService': {
          'Create': sysroot.SysrootCreateResponse,
          'GenerateArchive': sysroot.SysrootGenerateArchiveResponse,
          'InstallToolchain': sysroot.InstallToolchainResponse,
          'InstallPackages': sysroot.InstallPackagesResponse,
      },
      'TestService': {
          'BazelTest': empty_pb2.Empty,
          'BuildTargetUnitTest': test.BuildTargetUnitTestResponse,
          'BuildTestServiceContainers': test.BuildTestServiceContainersResponse,
          'ChromitePytest': empty_pb2.Empty,
          'ChromiteUnitTest': empty_pb2.Empty,
          'DebugInfoTest': empty_pb2.Empty,
          'RulesCrosUnitTest': empty_pb2.Empty,
          'VmTest': empty_pb2.Empty,
      },
      'ToolchainService': {
          'PrepareForBuild': toolchain.PrepareForToolchainBuildResponse,
          'BundleArtifacts': toolchain.BundleToolchainResponse,
          'SetupToolchains': toolchain.SetupToolchainsResponse,
      },
      'VersionService': {
          'Get': meta_api.VersionGetResponse,
      }
  }

  responses_by_service = api.cros_build_api.test_api.responses_by_service()
  for service, responses_by_method in responses_by_service.items():
    for method, response_json in responses_by_method.items():
      api.assertions.assertIn(service, response_type_by_service)
      api.assertions.assertIn(method, response_type_by_service[service])

      # Check we can create a valid response proto.
      response_type = response_type_by_service[service][method]
      _ = response_type(**json.loads(response_json))

  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.BadService/Foo')
  api.assertions.assertRaises(KeyError,
                              api.cros_build_api.test_api.response_for_endpoint,
                              'chromite.api.ArtifactsService/BadMethod')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'basic-with-output',
      api.properties(
          **{
              # This property is needed to capture tee_log output of build_api.
              '$chromeos/cros_build_api':
                  CrosBuildApiProperties(capture_stdout_stderr=True,
                                         publish_emerge_stats_to_bq=True,
                                         publish_emerge_stats_to_prop=True),
          }),
  )
