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

import datetime

# infra/proto/src/chromiumos/builder_report.proto
from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.chromiumos.common import Channel
from PB.chromite.api.packages import GetBuilderMetadataResponse
from recipe_engine.recipe_api import StepFailure

BuildStatus = BuildReport.BuildStatus


def RunSteps(api):
  # test that we can't set an invalid value for build_type
  api.assertions.assertRaisesRegexp(
      ValueError,
      "Invalid build type",
      api.build_reporting.set_build_type,
      -42,
  )

  # test that we have to set the build type before sending anything
  api.assertions.assertRaisesRegexp(
      RuntimeError,
      "Build type must be set before sending first message.",
      api.build_reporting.publish_status,
      BuildStatus.RUNNING,
  )

  # basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)
  api.assertions.assertEqual(
      api.build_reporting.build_type,
      BuildReport.BUILD_TYPE_RELEASE,
  )

  # test that we can't send a message that's not a BuildReport
  api.assertions.assertRaisesRegexp(TypeError, "Can only publish BuildReport",
                                    api.build_reporting.publish, {})

  # test that we can only set the build type once
  api.assertions.assertRaisesRegexp(
      RuntimeError,
      "only be set once",
      api.build_reporting.set_build_type,
      BuildReport.BUILD_TYPE_RELEASE,
  )

  # Test that we can't send process builder meta with multiple build targets.
  response = GetBuilderMetadataResponse()
  response.build_target_metadata.add()
  response.build_target_metadata.add()
  api.assertions.assertRaisesRegexp(
      StepFailure, "build_target_metadata must have a single element",
      api.build_reporting.publish_build_target_and_model_metadata, 'branch',
      response)

  api.build_reporting.publish_status(BuildStatus.RUNNING)
  response = GetBuilderMetadataResponse()
  build = response.build_target_metadata.add()
  build.fingerprints.append('fingerprint')
  build.android_container_target = 'target-1234'
  response.model_metadata.add()
  api.build_reporting.publish_build_target_and_model_metadata(
      'release-R12-12345.B', response)

  # check that we can create a raw build report instance
  build_report = api.build_reporting.create_build_report()

  # publish config information about the build
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
      api.time.utcnow() + datetime.timedelta(hours=5),
      api.build_reporting.STEP_SUCCESS,
  )
  step_info.publish()

  api.assertions.assertRaisesRegexp(
      ValueError,
      "should start with gs://",
      api.build_reporting.publish_build_artifact,
      None,
      "some_uri",
      "some_hash",
  )

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
  api.assertions.assertEqual(build_report.config.android_container_target.name,
                             'target-1234')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'basic-staging',
      api.buildbucket.generic_build(builder="staging-backfiller"),
  )
