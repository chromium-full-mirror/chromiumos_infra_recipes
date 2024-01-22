# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.assertions.assertEqual(
      api.cros_artifacts.artifacts_by_image_type[common.IMAGE_TYPE_RECOVERY],
      'recovery_image.tar.xz',
  )

  target = common.BuildTarget()
  target.name = 'target'

  artifacts_info = common.ArtifactsByService(
      legacy=common.ArtifactsByService.Legacy(output_artifacts=[
          common.ArtifactsByService.Legacy.ArtifactInfo(
              artifact_types=[common.ArtifactsByService.Legacy.EBUILD_LOGS])
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
      infra=common.ArtifactsByService.Infra(output_artifacts=[
          common.ArtifactsByService.Infra.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Infra.BUILD_MANIFEST,
          ])
      ]),
  )

  # This verifies that we can upload artifacts, some of which get an acl
  # applied.  Legacy and Toolchain artifacts get us coverage of both paths in
  # the API 1.0.0 case.
  uploaded, _ = api.cros_artifacts.upload_artifacts(
      'target-toolchain', BuilderConfig.Id.TOOLCHAIN, 'artifacts_gs_bucket',
      artifacts_info=artifacts_info,
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/{}'.format(target.name),
                              build_target=target))

  api.cros_artifacts.upload_metadata(
      'test',
      'target-toolchain',
      target.name,
      'artifacts_gs_bucket',
      'metadata',
      BuilderConfig(),  # Just used as a proto Message for testing
  )

  api.cros_artifacts.push_image(
      chroot=common.Chroot(path='/path/to/chroot'),
      gs_image_dir='gs://chromeos-image-archive/atlas-release/R89-13604.0.0',
      sysroot=sysroot.Sysroot(build_target=common.BuildTarget(name='atlas')),
      dryrun=True)

  # The uploaded properties should reflect calls to upload_artifacts with
  # different sysroots.  Currently, this is only used by some builders
  # supporting legacy branches.
  api.cros_artifacts.merge_artifacts_properties([uploaded, uploaded])


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.MustRun,
                     'upload artifacts.publish artifacts'))

  yield api.test(
      'dry-run', api.cq(run_mode=api.cq.DRY_RUN), api.buildbucket.try_build(),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'))

  yield api.test(
      'firmware-cq', api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          data=('{"artifacts": {"artifacts": [{"artifact_type":"FIRMWARE_LCOV",'
                '"paths": [{"path":"[START_DIR]/coverage.tbz2","location":2}],'
                '"location": "PLATFORM_EC"},'
                '{"artifact_type":"CODE_COVERAGE_HTML",'
                '"paths": [{"path":"[START_DIR]/html.tbz2","location":2}],'
                '"location": "PLATFORM_EC"}]}}')))

  yield api.test('no-ArtifactsService/Get',
                 api.cros_build_api.remove_endpoints(['ArtifactsService/Get']))

  yield api.test(
      'upload-artifacts-exception',
      api.cros_build_api.set_api_return(
          parent_step_name='upload artifacts.call artifacts service',
          endpoint='ArtifactsService/Get', retcode=1),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE')

  yield api.test(
      'skip-publish',
      api.properties(**{
          '$chromeos/cros_artifacts':
              CrosArtifactsProperties(skip_publish=True),
      }),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_process(post_process.DropExpectation),
  )
