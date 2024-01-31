# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercise all the functionality of the build_reporting module."""

from RECIPE_MODULES.chromeos.cros_artifacts import api as cros_artifacts_api
from RECIPE_MODULES.chromeos.cros_sdk import api as cros_sdk_api

from PB.chromite.api.packages import GetTargetVersionsResponse
from PB.chromiumos.build_report import BuildReport, URI
from PB.chromiumos.common import Channel
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'build_reporting',
]


BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails

PARENT_ID = 8832734656515626817


def RunSteps(api):
  # basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')
  api.build_reporting.publish_status(BuildStatus.RUNNING)

  # publish config information about the build
  build_report = api.build_reporting.create_build_report()
  config = build_report.config
  config.branch.name = 'release-R12-12345.B'

  config.models.add().name = 'fooble'
  config.models.add().name = 'barble'
  config.models.add().name = 'bazble'
  build_report.publish()

  # build some stuff
  step_info = api.build_reporting.create_step_info(
      BuildReport.StepDetails.STEP_SYNC,
      api.time.utcnow(),
  )
  step_info.publish()

  # sync the tree
  step_info.runtime.end.FromDatetime(api.time.utcnow())
  step_info.status = StepDetails.STATUS_SUCCESS
  step_info.publish()

  api.build_reporting.publish_build_artifacts(
      cros_artifacts_api.UploadedArtifacts(
          'chromeos-image-archive',
          'build_target-release/R12-12345.0.0',
          {
              'DEBUG_SYMBOLS': ['debug.tgz',],
              'FACTORY_IMAGE': ['factory_image.zip'],
              'FIRMWARE': ['firmware_from_source.tar.bz2'],
              'IMAGE_ARCHIVES': [
                  'chromiumos_base_image.tar.xz',
                  # The file we're looking for.
                  'chromiumos_test_image.tar.xz',
                  'recovery_image.tar.xz',
                  'vmlinuz.tar.xz'
              ],
              'IMAGE_ZIP': ['image.zip'],
              'HWQUAL': ['chromeos-hwqual-build_target-R78-12438.0.0.tar.bz2'],
              # Unsupported, should not be included in pubsub.
              'SDK_TARBALL': ['/path/to/tarball.tgz',]
          }),
      '/path/to/artifacts')

  # No additional calls allowed.
  with api.assertions.assertRaises(StepFailure):
    api.build_reporting.publish_build_artifacts(
        cros_artifacts_api.UploadedArtifacts(
            'chromeos-image-archive', 'build_target-release/R12-12345.0.0', {}),
        '/path/to/artifacts')

  # Publish the branch.
  api.build_reporting.publish_branch('main')

  # Publish channels.
  api.build_reporting.publish_channels([
      Channel.CHANNEL_CANARY,
      Channel.CHANNEL_DEV,
  ])

  # Publish the versions.
  vers = GetTargetVersionsResponse(
      android_version='5812377', android_branch_version='git_nyc',
      android_target_version='cheets', chrome_version='78.0.3877.0',
      full_version='R78-12438.0.0', milestone_version='78',
      platform_version='12438.0.0')
  api.build_reporting.publish_versions(vers)

  # Publish SDK/toolchain metadata.
  sdk_version = '2022.06.26.170938'
  sdk_bucket = 'chromiumos-sdk'
  toolchain_url = '2022/06/%(target)s-2022.06.26.170938.tar.xz'
  toolchains = ['x86_64-cros-linux-gnu', 'i686-cros-linux-gnu']
  api.build_reporting.publish_toolchain_info(
      cros_sdk_api.ToolchainInfo(
          sdk_version=sdk_version,
          sdk_bucket=sdk_bucket,
          toolchain_url=toolchain_url,
          toolchains=toolchains,
      ))
  # No additional calls allowed.
  with api.assertions.assertRaises(StepFailure):
    api.build_reporting.publish_toolchain_info(
        cros_sdk_api.ToolchainInfo(
            sdk_version=sdk_version,
            sdk_bucket=sdk_bucket,
            toolchain_url=toolchain_url,
            toolchains=toolchains,
        ))

  # ...

  # finalize build status
  api.build_reporting.publish_status(BuildStatus.SUCCESS)

  # check presence of fields in final aggregated report
  build_report = api.build_reporting.merged_build_report
  api.assertions.assertEqual(
      build_report.buildbucket_id,
      api.buildbucket.build.id,
  )
  api.assertions.assertEqual(build_report.status.value, BuildStatus.SUCCESS)
  api.assertions.assertTrue(build_report.HasField('config'))
  api.assertions.assertTrue(build_report.HasField('steps'))
  api.assertions.assertEqual(len(build_report.steps.info), 1)
  api.assertions.assertEqual(build_report.parent.buildbucket_id, PARENT_ID)
  api.assertions.assertEqual(build_report.sdk_version, sdk_version)
  api.assertions.assertEqual(build_report.toolchain_url, toolchain_url)
  api.assertions.assertEqual(build_report.toolchains, toolchains)
  api.assertions.assertEqual(build_report.config.release.channels, [
      Channel.CHANNEL_CANARY,
      Channel.CHANNEL_DEV,
  ])
  api.assertions.assertEqual(len(build_report.artifacts), 6)
  api.assertions.assertEqual(
      list(build_report.artifacts), [
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.DEBUG_ARCHIVE,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/debug.tgz',
              ),
              sha256='deadbeef',
              size=111,
          ),
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.FACTORY_IMAGE_ZIP,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/factory_image.zip',
              ),
              sha256='deadbeef',
              size=111,
          ),
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.FIRMWARE_IMAGE_ARCHIVE,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/firmware_from_source.tar.bz2',
              ),
              sha256='deadbeef',
              size=111,
          ),
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.TEST_IMAGE_ARCHIVE,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/chromiumos_test_image.tar.xz',
              ),
              sha256='deadbeef',
              size=111,
          ),
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.IMAGE_ZIP,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/image.zip',
              ),
              sha256='deadbeef',
              size=111,
          ),
          BuildReport.BuildArtifact(
              type=BuildReport.BuildArtifact.HWQUAL_ARCHIVE,
              uri=URI(
                  gcs='gs://chromeos-image-archive/build_target-release/R12-12345.0.0/chromeos-hwqual-build_target-R78-12438.0.0.tar.bz2',
              ),
              sha256='deadbeef',
              size=111,
          ),
      ])


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.build(
          build_pb2.Build(
              tags=[{
                  'key': 'parent_buildbucket_id',
                  'value': str(PARENT_ID),
              }],
          ),
      ))
