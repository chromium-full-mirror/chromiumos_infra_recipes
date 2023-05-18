# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from recipe_engine import post_process
from recipe_engine.recipe_api import Property

PROPERTIES = {
    'exclude_image_archives':
        Property(
            help='Whether to define the artifact_info with no IMAGE_ARCHIVES type.',
            kind=bool, default=False),
}

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api, exclude_image_archives):
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
                  .UNVERIFIED_CHROME_LLVM_ORDERFILE
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
      infra=common.ArtifactsByService.Infra(output_artifacts=[
          common.ArtifactsByService.Infra.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Infra.BUILD_MANIFEST,
          ])
      ]),
  )

  if exclude_image_archives:
    artifacts_info.legacy.Clear()

  api.cros_artifacts.upload_artifacts(
      'builder', BuilderConfig.Id.Type.RELEASE, 'test-bucket',
      artifacts_info=artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')),
      report_to_spike=True, attestation_eligible=True)


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
