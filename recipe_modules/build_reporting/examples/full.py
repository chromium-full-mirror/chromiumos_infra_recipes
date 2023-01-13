# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api.packages import GetTargetVersionsResponse
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import Channel
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'build_reporting',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails

PARENT_ID = 8832734656515626817


def RunSteps(api):
  # basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     "build_target")
  api.build_reporting.publish_status(BuildStatus.RUNNING)

  # publish config information about the build
  build_report = api.build_reporting.create_build_report()
  config = build_report.config
  config.branch.name = "release-R12-12345.B"

  config.release.channels.append(Channel.CHANNEL_BETA)
  config.release.channels.append(Channel.CHANNEL_DEV)
  config.release.channels.append(Channel.CHANNEL_CANARY)

  config.models.add().name = "fooble"
  config.models.add().name = "barble"
  config.models.add().name = "bazble"
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

  api.build_reporting.publish_build_artifact(
      BuildReport.BuildArtifact.RELEASE_IMAGE,
      "gs://chromeos-image-archive/garble.tgz",
      "3457ed415f59b37aab2a2fd80382f782c70391c2b25396abd833892f5b5eef60",
  )

  # Publish the branch.
  api.build_reporting.publish_branch('main')

  # Publish the versions.
  vers = GetTargetVersionsResponse(
      android_version='5812377', android_branch_version='git_nyc',
      android_target_version='cheets', chrome_version='78.0.3877.0',
      full_version='R78-12438.0.0', milestone_version='78',
      platform_version='12438.0.0')
  api.build_reporting.publish_versions(vers)

  # Publish SDK/toolchain metadata.
  sdk_version = '2022.06.26.170938'
  toolchain_url = '2022/06/%(target)s-2022.06.26.170938.tar.xz'
  toolchains = ['x86_64-cros-linux-gnu', 'i686-cros-linux-gnu']
  api.build_reporting.publish_toolchain_info(
      api.cros_sdk.ToolchainInfo(
          sdk_version,
          toolchain_url,
          toolchains,
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
  api.assertions.assertEqual(len(build_report.artifacts), 1)
  api.assertions.assertTrue(build_report.HasField("config"))
  api.assertions.assertTrue(build_report.HasField("steps"))
  api.assertions.assertEqual(len(build_report.steps.info), 1)
  api.assertions.assertEqual(build_report.parent.buildbucket_id, PARENT_ID)
  api.assertions.assertEqual(build_report.sdk_version, sdk_version)
  api.assertions.assertEqual(build_report.toolchain_url, toolchain_url)
  api.assertions.assertEqual(build_report.toolchains, toolchains)


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
