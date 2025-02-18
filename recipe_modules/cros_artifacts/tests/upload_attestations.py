# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for generating BCID attestations for artifacts."""

import json

from google.protobuf.json_format import MessageToDict

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties
from PB.recipe_modules.chromeos.cros_artifacts.tests.upload_attestations import \
    UploadAttestationsProperties
from recipe_engine import post_process

PROPERTIES = UploadAttestationsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]



def RunSteps(api, properties):
  artifacts_info = common.ArtifactsByService(
      legacy=common.ArtifactsByService.Legacy(output_artifacts=[
          common.ArtifactsByService.Legacy.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Legacy.IMAGE_ARCHIVES,
          ])
      ]),
      toolchain=common.ArtifactsByService.Toolchain(output_artifacts=[
          common.ArtifactsByService.Toolchain.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Toolchain
                  .UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE
              ], gs_locations=['publish_gs_location', 'pub2/{gs_path}'],
              acl_name='public-read')
      ]),
      firmware=common.ArtifactsByService.Firmware(output_artifacts=[
          common.ArtifactsByService.Firmware.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Firmware.FIRMWARE_TARBALL,
                  common.ArtifactsByService.Firmware.FIRMWARE_TARBALL_INFO,
                  common.ArtifactsByService.Firmware.FIRMWARE_LCOV,
                  common.ArtifactsByService.Firmware.CODE_COVERAGE_HTML,
              ], acl_name='public-read')
      ]),
      sysroot=common.ArtifactsByService.Sysroot(output_artifacts=[
          common.ArtifactsByService.Sysroot.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Sysroot.DEBUG_SYMBOLS,
                  common.ArtifactsByService.Sysroot.BREAKPAD_DEBUG_SYMBOLS,
              ], acl_name='public-read')
      ]),
      infra=common.ArtifactsByService.Infra(output_artifacts=[
          common.ArtifactsByService.Infra.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Infra.BUILD_MANIFEST,
          ])
      ]),
  )

  if properties.exclude_image_archives:
    artifacts_info.legacy.Clear()

  api.cros_artifacts.upload_artifacts(
      'builder', BuilderConfig.Id.Type.RELEASE, 'test-bucket',
      artifacts_info=artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')),
      report_to_spike=True, attestation_eligible=True,
      ignore_breakpad_symbol_generation_errors=properties
      .ignore_breakpad_symbol_generation_errors)


def GenTests(api):

  yield api.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps({
              'artifacts': [{
                  'path': 'chromiumos_base_image.tar.xz',
              }],
          }, sort_keys=True)),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
  )

  yield api.test(
      'ignore-breakpad-symbol-generation-errors',
      api.properties(ignore_breakpad_symbol_generation_errors=True),
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps({
              'artifacts': [{
                  'path': 'chromiumos_base_image.tar.xz',
              }],
          }, sort_keys=True)),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
  )

  yield api.test(
      'image-archives-does-not-exist',
      api.properties(exclude_image_archives=True),
      api.post_process(
          post_process.DoesNotRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(post_process.LogEquals, 'upload artifacts',
                       'report_to_spike',
                       'IMAGE_ARCHIVES not in files_by_artifact'),
  )

  yield api.test(
      'local-dlcs-with-failure-and-retry',
      api.step_data(
          'upload artifacts.Find DLCs.list local DLCs',
          api.file.listdir([
              'fake/dlc.img', 'fake2/dlc.img', 'fake3/dlc.img', 'fake4/dlc.img'
          ]),
      ),
      api.post_check(post_process.MustRun,
                     'upload artifacts.Find DLCs.list local DLCs'),
      # First DLC which succeeds on report
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake/dlc.img"]),
      # Second DLC fails
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (2)',
          retcode=1),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (2)',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake2/dlc.img"]),
      # Retry for DLC2. If we get a snoopy error uploading the attestation for fake2/dlc.img
      # we should retry it before moving on to the next DLC.
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (3)',
          retcode=1),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (3)',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake2/dlc.img"]),
      # Second retry for DLC 2.
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (4)',
          retcode=1),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (4)',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake2/dlc.img"]),
      # Give up on DLC2 and move onto DLC 3 & 4.
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (5)',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake3/dlc.img"]),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (6)',
          ["gs://test-bucket/builder/R99-1234.56.0-101-/dlc/fake4/dlc.img"]),
      status='SUCCESS')

  yield api.test(
      'provenance-failure-with-enforcement',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  MessageToDict(
                      CrosArtifactsProperties(bcid_enforcement={
                          'upload_artifact_prov_generation_fatal': True
                      })),
          }),
      api.step_data(
          'upload artifacts.Find DLCs.list local DLCs',
          api.file.listdir([
              'fake/dlc.img', 'fake2/dlc.img', 'fake3/dlc.img', 'fake4/dlc.img'
          ]),
      ),
      # We do 3 retries, and all 3 must fail in order for the step to fail.
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs',
          retcode=1,
      ),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (2)',
          retcode=1,
      ),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (3)',
          retcode=1,
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')
