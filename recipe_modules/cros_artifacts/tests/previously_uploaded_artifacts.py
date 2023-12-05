# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from PB.chromite.api.artifacts import GetRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.firmware import BundleFirmwareArtifactsRequest, BcsVersionInfo
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService, BuildTarget, ResultPath, Path
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  artifacts_info = ArtifactsByService(
      legacy=ArtifactsByService.Legacy(output_artifacts=[
          ArtifactsByService.Legacy.ArtifactInfo(
              artifact_types=[ArtifactsByService.Legacy.EBUILD_LOGS])
      ]),
      toolchain=ArtifactsByService.Toolchain(output_artifacts=[
          ArtifactsByService.Toolchain.ArtifactInfo(
              artifact_types=[
                  ArtifactsByService.Toolchain
                  .UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE
              ], gs_locations=['publish_gs_location', 'pub2/{gs_path}'],
              acl_name='public-read')
      ]),
      firmware=ArtifactsByService.Firmware(output_artifacts=[
          ArtifactsByService.Firmware.ArtifactInfo(
              artifact_types=[
                  ArtifactsByService.Firmware.FIRMWARE_TARBALL,
                  ArtifactsByService.Firmware.FIRMWARE_TARBALL_INFO,
                  ArtifactsByService.Firmware.FIRMWARE_LCOV,
                  ArtifactsByService.Firmware.CODE_COVERAGE_HTML,
              ], acl_name='public-read')
      ]),
  )

  # UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE and FIRMWARE_TARBALL were previously
  # uploaded, so should not be re-uploaded. Note that
  # ArtifactsByService.Legacy. will be re-uploaded, even though it was
  # previously uploaded.
  previously_uploaded_artifacts = api.cros_artifacts.UploadedArtifacts(
      gs_bucket='test_bucket', gs_path='builder/R99-1234.56.0-101-',
      files_by_artifact={
          'EBUILD_LOGS': ['../../[START_DIR]/tmp/artifact.tar.gz'],
          'UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE': ['testafdofile'],
          'FIRMWARE_TARBALL': ['../../[START_DIR]/from_source.tar.bz2'],
      })

  api.cros_artifacts.upload_artifacts(
      'builder', BuilderConfig.Id.CQ, 'test_bucket',
      artifacts_info=artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')),
      previously_uploaded_artifacts=previously_uploaded_artifacts)


def GenTests(api):
  # Expect all firmware types except FIRMWARE_TARBALL to be uploaded.
  expected_firmware_req = BundleFirmwareArtifactsRequest(
      result_path=ResultPath(
          path=Path(path='[CLEANUP]/artifacts_tmp_1', location=Path.OUTSIDE),
      ),
      artifacts=ArtifactsByService.Firmware(output_artifacts=[
          ArtifactsByService.Firmware.ArtifactInfo(
              artifact_types=[
                  ArtifactsByService.Firmware.FIRMWARE_TARBALL_INFO,
                  ArtifactsByService.Firmware.FIRMWARE_LCOV,
                  ArtifactsByService.Firmware.CODE_COVERAGE_HTML,
              ], acl_name='public-read')
      ]),
      bcs_version_info=BcsVersionInfo(version_string='R99-1234.56.0-101'),
  )

  # Expect all firmware types except FIRMWARE_TARBALL to be uploaded. Note that
  # EBUILD_LOGS will be re-uploaded.
  expected_get_req = GetRequest(
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')),
      artifact_info=ArtifactsByService(
          legacy=ArtifactsByService.Legacy(output_artifacts=[
              ArtifactsByService.Legacy.ArtifactInfo(artifact_types=[
                  ArtifactsByService.Legacy.EBUILD_LOGS,
              ])
          ]), toolchain=ArtifactsByService.Toolchain(),
          firmware=ArtifactsByService.Firmware(output_artifacts=[
              ArtifactsByService.Firmware.ArtifactInfo(
                  artifact_types=[
                      ArtifactsByService.Firmware.FIRMWARE_TARBALL_INFO,
                      ArtifactsByService.Firmware.FIRMWARE_LCOV,
                      ArtifactsByService.Firmware.CODE_COVERAGE_HTML,
                  ], acl_name='public-read'),
          ])),
      result_path=ResultPath(
          path=Path(path='[CLEANUP]/artifacts_tmp_1', location=Path.OUTSIDE),
      ),
  )

  yield api.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.post_process(
          post_process.LogEquals,
          'upload artifacts.call chromite.api.FirmwareService/BundleFirmwareArtifacts',
          'request',
          json_format.MessageToJson(expected_firmware_req,
                                    use_integers_for_enums=True)),
      api.post_process(
          post_process.LogEquals,
          'upload artifacts.call artifacts service.call chromite.api.ArtifactsService/Get',
          'request',
          json_format.MessageToJson(expected_get_req,
                                    use_integers_for_enums=True)),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.bundle EBUILD_LOGS for upload.call chromite.api.ArtifactsService/BundleEbuildLogs',
      ),
      # The artifacts property should contain previously uploaded artifact types
      # (UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE in this case).
      api.post_process(
          post_process.PropertyEquals, 'artifacts', {
              'files_by_artifact': {
                  'EBUILD_LOGS': ['../../[START_DIR]/tmp/artifact.tar.gz'],
                  'FIRMWARE_TARBALL': ['../../[START_DIR]/from_source.tar.bz2'],
                  'FIRMWARE_TARBALL_INFO':
                      ['../../[START_DIR]/fw_metadata.json'],
                  'FIRMWARE_TOKEN_DATABASE': ['../../[START_DIR]/tokens.bin'],
                  'UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE': ['testafdofile']
              },
              'gs_bucket': 'test_bucket',
              'gs_path': 'builder/R99-1234.56.0-101-'
          }),
      api.post_process(post_process.DoesNotRunRE,
                       'upload artifacts.call chromite.api.ToolchainService.*'),
  )
