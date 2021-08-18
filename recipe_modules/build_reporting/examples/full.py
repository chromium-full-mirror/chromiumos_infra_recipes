# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'build_reporting',
]

# infra/proto/src/chromiumos/builder_report.proto
from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.chromiumos.common import Channel

BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails


def RunSteps(api):
  # basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)
  api.build_reporting.publish_status(BuildStatus.RUNNING)

  # publish config information about the build
  config = api.build_reporting.create_build_config()
  config.branch.name = "release-R12-12345.B"
  config.release.milestone = 12
  config.release.build = "12345.123.0"
  config.release.channels.append(Channel.CHANNEL_BETA)
  config.release.channels.append(Channel.CHANNEL_DEV)
  config.release.channels.append(Channel.CHANNEL_CANARY)
  config.models.add().name = "fooble"
  config.models.add().name = "barble"
  config.models.add().name = "bazble"
  config.publish()

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


def GenTests(api):
  yield api.test('basic')
