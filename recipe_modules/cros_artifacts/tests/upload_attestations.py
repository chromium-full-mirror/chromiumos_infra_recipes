# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json
import re

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
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
      'local-dlcs',
      api.step_data(
          'upload artifacts.Find DLCs.list local DLCs',
          api.file.listdir(['fake/dlc.img', 'fake2/dlc.img']),
      ),
      api.post_check(post_process.MustRun,
                     'upload artifacts.Find DLCs.list local DLCs'),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs (2)'),
      # Exactly 2 artifacts to report.
      api.post_process(
          post_process.DoesNotRun,
          'upload artifacts.generate provenance.snoop: report_gcs (3)'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs',
          [re.compile(r'gs:\/\/.*\/fake\/dlc\.img')]),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (2)',
          [re.compile(r'gs:\/\/.*\/fake2\/dlc\.img')]),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'provenance-failure',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps({
              'artifacts': [{
                  'path': 'chromiumos_base_image.tar.xz',
              }],
          }, sort_keys=True)),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs',
          retcode=1,
      ), api.post_process(post_process.DropExpectation))
