# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that triggers cros_test_platform runs.
"""

from google.protobuf import duration_pb2
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2
from google.protobuf.json_format import MessageToDict

from PB.recipes.chromeos.test_platform.ctp_traffic_generator import Properties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.test_platform.request import Request

from recipe_engine import post_process

PROPERTIES = Properties
DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_platform',
    'skylab',
]

TIMEOUT_SECONDS = 30 * 60  # 30 minutes
DEFAULT_CTP_REPLAY_MAX_RUNTIME = 20 * 60
CTP_BUILDS_TO_REPLAY = 2
REPLAYED_PROD_BUILD_ID_TAG = 'replay_from_prod_buildbucket_id'


def RunSteps(api, properties):
  ctp_replay_max_runtime = properties.ctp_replay_max_runtime or DEFAULT_CTP_REPLAY_MAX_RUNTIME
  ctp_num_replay_builds = properties.ctp_num_replay_builds or CTP_BUILDS_TO_REPLAY

  # Replay the last two successful production CTP builds in staging to
  # seed staging with real requests.
  with api.step.nest('replay prod CTP run'):
    _replay_successful_ctp_builds_in_staging(api, ctp_num_replay_builds,
                                             ctp_replay_max_runtime)


def _get_last_successful_ctp_builds(api, num_builds=CTP_BUILDS_TO_REPLAY,
                                    time_limit_seconds=TIMEOUT_SECONDS):
  # Only search up to 6 hrs back to make sure we replay relevant prod CTP data.
  six_hours_back = _bb_time_range(api, 6 * 60)
  ctp_builder = 'cros_test_platform'
  successful_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': ctp_builder,
          }, status=bb_common.SUCCESS, create_time=six_hours_back),
      fields=['*'], step_name='find recent green %s builds' % ctp_builder)
  if not successful_builds:
    raise api.step.StepFailure('No successful builds found for builder %s' %
                               ctp_builder)

  already_replayed_build_ids = _already_replayed_ctp_build_ids(
      api, six_hours_back)

  builds = []
  for build in successful_builds:
    run_time = build.end_time.seconds - build.start_time.seconds
    # If run time is less than time_limit_seconds, use the build.
    # Otherwise keep looking.
    if run_time < time_limit_seconds and build.id not in already_replayed_build_ids:
      builds.append(build)
      if len(builds) == num_builds:
        break
  if not builds:
    raise api.step.StepFailure(
        'No new successful builds with completion time under {}s found for builder {}'
        .format(time_limit_seconds, ctp_builder))
  return builds


def _already_replayed_ctp_build_ids(api, time_range):
  ctp_staging_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform-staging',
          }, create_time=time_range), fields=['*'],
      step_name='filter out already-replayed builds')

  replayed_prod_build_ids = []
  for staging_build in ctp_staging_builds:
    for tag in staging_build.tags:
      if tag.key == REPLAYED_PROD_BUILD_ID_TAG:
        replayed_prod_build_ids.append(int(tag.value))
        break
  return replayed_prod_build_ids


def _bb_time_range(api, start_minutes_back, end_minutes_back=0):
  current_timestamp_seconds = api.buildbucket.build.create_time.ToSeconds()
  return bb_common.TimeRange(
      start_time=timestamp_pb2.Timestamp(seconds=current_timestamp_seconds -
                                         60 * start_minutes_back),
      end_time=timestamp_pb2.Timestamp(seconds=current_timestamp_seconds -
                                       60 * end_minutes_back))


def _replay_successful_ctp_builds_in_staging(api, ctp_num_replay_builds,
                                             time_limit_seconds):
  builds = _get_last_successful_ctp_builds(
      api, num_builds=ctp_num_replay_builds,
      time_limit_seconds=time_limit_seconds)
  for build in builds:
    reqs = MessageToDict(build.input.properties["requests"])
    bb_tags = {
        REPLAYED_PROD_BUILD_ID_TAG: str(build.id),
        'parent_buildbucket_id': str(api.buildbucket.build.id)
    }
    api.skylab.schedule_ctp_requests(tagged_requests=reqs, bb_tags=bb_tags)


def GenTests(api):
  ctp_input_properties = struct_pb2.Struct()
  ctp_input_properties['requests'] = {
      "gale_gale": {
          "params": {
              "decorations": {
                  "tags": [
                      "label-board:gale", "analytics_name:RLZ",
                      "label-model:gale", "build:gale-release/R89-13729.57.2",
                      "suite:rlz", "ctp-fwd-task-name:RLZ",
                      "label-pool:MANAGED_POOL_QUOTA"
                  ]
              },
              "hardwareAttributes": {
                  "model": "gale"
              },
              "metadata": {
                  "debugSymbolsArchiveUrl":
                      "gs://chromeos-image-archive/gale-release/R89-13729.57.2",
                  "testMetadataUrl":
                      "gs://chromeos-image-archive/gale-release/R89-13729.57.2"
              },
              "retry": {
                  "allow": True,
                  "max": 3
              },
              "scheduling": {
                  "managedPool": "MANAGED_POOL_QUOTA",
                  "qsAccount": "legacypool-suites"
              },
              "softwareAttributes": {
                  "buildTarget": {
                      "name": "gale"
                  }
              },
              "softwareDependencies": [{
                  "chromeosBuild": "gale-release/R89-13729.57.2"
              }],
              "time": {
                  "maximumDuration": "153000s"
              }
          },
          "testPlan": {
              "suite": [{
                  "name": "rlz"
              }]
          }
      }
  }
  green_ctp_builds = [
      # This build should always be skipped since it was previously replayed.
      build_pb2.Build(
          id=100,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 5),
          status='SUCCESS',
          input={'properties': ctp_input_properties},
      ),
      build_pb2.Build(
          id=123,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 65),
          status='SUCCESS',
          input={'properties': ctp_input_properties},
      ),
      build_pb2.Build(
          id=456,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 15),
          status='SUCCESS',
          input={'properties': ctp_input_properties},
      ),
      build_pb2.Build(
          id=789,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': ctp_input_properties},
      )
  ]
  previous_ctp_staging_runs = [
      build_pb2.Build(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform-staging',
          }, tags=[
              bb_common.StringPair(key=REPLAYED_PROD_BUILD_ID_TAG, value='100')
          ]),
  ]

  yield api.test(
      'successful run',
      api.properties(**{
          'ctp_replay_max_runtime': 70 * 60,
          'ctp_num_replay_builds': 3,
      }),
      api.buildbucket.simulated_search_results(
          green_ctp_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_ctp_staging_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
  )

  yield api.test(
      'ctp prod build not found',
      api.buildbucket.simulated_search_results(
          [],
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ))

  yield api.test(
      'ctp build not found matching runtime limit',
      api.properties(**{
          'ctp_replay_max_runtime': 60 * 10,
      }),
      api.buildbucket.simulated_search_results(
          green_ctp_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_ctp_staging_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
      api.post_check(post_process.StepFailure, 'replay prod CTP run'),
  )
