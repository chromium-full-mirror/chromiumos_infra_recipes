# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that triggers cros_test_platform runs.
"""

from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2
from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.test_platform.ctp_traffic_generator import Properties
from recipe_engine import post_process

PROPERTIES = Properties
DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_platform',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

TIMEOUT_SECONDS = 30 * 60  # 30 minutes
DEFAULT_CTP_REPLAY_MAX_RUNTIME = 20 * 60
CTP_BUILDS_TO_REPLAY = 10
REPLAYED_PROD_BUILD_ID_TAG = 'replay_from_prod_buildbucket_id'

MAX_CFT_BUILDS = 7
MAX_PHOSPHORUS_BUILDS = 3


def RunSteps(api, properties):
  ctp_replay_max_runtime = properties.ctp_replay_max_runtime or DEFAULT_CTP_REPLAY_MAX_RUNTIME
  ctp_num_replay_builds = properties.ctp_num_replay_builds or CTP_BUILDS_TO_REPLAY

  # Replay the last two successful production CTP builds in the replay builder
  # (e.g. cros_test_platform-staging) to seed it with real requests.
  with api.step.nest('replay prod CTP run'):
    _replay_successful_ctp_builds_in_replay_builder(api, properties.ctp_builder,
                                                    ctp_num_replay_builds,
                                                    ctp_replay_max_runtime)


def _get_last_successful_ctp_prod_builds(api, replay_builder,
                                         num_builds=CTP_BUILDS_TO_REPLAY,
                                         time_limit_seconds=TIMEOUT_SECONDS):
  # Only search up to 6 hrs back to make sure we replay relevant prod CTP data.
  six_hours_back = _bb_time_range(api, 12 * 60)
  ctp_prod_builder = 'cros_test_platform'
  successful_prod_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': ctp_prod_builder,
          }, status=bb_common.SUCCESS,
          create_time=six_hours_back), fields=['*'], limit=1000,
      step_name='find recent green %s builds' % ctp_prod_builder)
  if not successful_prod_builds:
    raise api.step.StepFailure('No successful builds found for builder %s' %
                               ctp_prod_builder)

  already_replayed_build_ids = _already_replayed_ctp_build_ids(
      api, replay_builder, six_hours_back)

  builds = []
  cft_builds = 0
  phosphorus_builds = 0
  for build in successful_prod_builds:
    is_cft_build = False

    run_time = build.end_time.seconds - build.start_time.seconds
    # If run time is less than time_limit_seconds, use the build.
    # Otherwise keep looking.
    if run_time < time_limit_seconds and build.id not in already_replayed_build_ids:

      # Check if build is a CFT build
      reqs = MessageToDict(build.input.properties['requests'])
      for _, req in reqs.items():
        if req.get('params') and req.get('params').get('runViaCft') is True:
          is_cft_build = True

      # Enforce a max ratio of CFT vs Phosphorus builds
      if is_cft_build and cft_builds < MAX_CFT_BUILDS:
        cft_builds += 1
        builds.append(build)
      elif phosphorus_builds < MAX_PHOSPHORUS_BUILDS:
        phosphorus_builds += 1
        builds.append(build)

      if len(builds) == num_builds:
        break
  if not builds:
    raise api.step.StepFailure(
        'No new successful builds with completion time under {}s found for builder {}'
        .format(time_limit_seconds, ctp_prod_builder))
  return builds


def _already_replayed_ctp_build_ids(api, replay_builder, time_range):
  ctp_builds_in_replay_builder = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': replay_builder,
          }, create_time=time_range), fields=['*'],
      step_name='filter out already-replayed builds')

  replayed_prod_build_ids = []
  for build in ctp_builds_in_replay_builder:
    for tag in build.tags:
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


def _replay_successful_ctp_builds_in_replay_builder(api, replay_builder,
                                                    ctp_num_replay_builds,
                                                    time_limit_seconds):
  builds = _get_last_successful_ctp_prod_builds(
      api, replay_builder, num_builds=ctp_num_replay_builds,
      time_limit_seconds=time_limit_seconds)
  for build in builds:
    reqs = MessageToDict(build.input.properties['requests'])
    new_reqs = _check_dev_env_and_cft(replay_builder, reqs)
    if not new_reqs:
      continue  # pragma: nocover
    bb_tags = {
        REPLAYED_PROD_BUILD_ID_TAG: str(build.id),
        'parent_buildbucket_id': str(api.buildbucket.build.id)
    }
    api.skylab.schedule_ctp_requests(tagged_requests=reqs, bb_tags=bb_tags)


# b/267268890: Only schedule cft requests in dev env. Remove after trv2
# rolls to prod.
def _check_dev_env_and_cft(replay_builder, reqs_dict):
  if not replay_builder.endswith('dev'):
    return reqs_dict

  new_reqs_dict = {}
  for tag, req in reqs_dict.items():
    if req.get('params') and req.get('params').get('runViaCft') is True:
      # Run the request in trv2
      req['params']['runViaTrv2'] = True
      new_reqs_dict[tag] = req

  return new_reqs_dict


def GenTests(api):
  cft_input_properties = struct_pb2.Struct()
  cft_input_properties['requests'] = {
      'gale_gale': {
          'params': {
              'decorations': {
                  'tags': [
                      'label-board:gale', 'analytics_name:RLZ',
                      'label-model:gale', 'build:gale-release/R89-13729.57.2',
                      'suite:rlz', 'ctp-fwd-task-name:RLZ',
                      'label-pool:MANAGED_POOL_QUOTA'
                  ]
              },
              'hardwareAttributes': {
                  'model': 'gale'
              },
              'metadata': {
                  'debugSymbolsArchiveUrl':
                      'gs://chromeos-image-archive/gale-release/R89-13729.57.2',
                  'testMetadataUrl':
                      'gs://chromeos-image-archive/gale-release/R89-13729.57.2'
              },
              'retry': {
                  'allow': True,
                  'max': 3
              },
              'runViaCft': True,
              'scheduling': {
                  'managedPool': 'MANAGED_POOL_QUOTA',
                  'qsAccount': 'legacypool-suites'
              },
              'softwareAttributes': {
                  'buildTarget': {
                      'name': 'gale'
                  }
              },
              'softwareDependencies': [{
                  'chromeosBuild': 'gale-release/R89-13729.57.2'
              }],
              'time': {
                  'maximumDuration': '153000s'
              }
          },
          'testPlan': {
              'suite': [{
                  'name': 'rlz'
              }]
          }
      }
  }

  phosphorus_input_properties = struct_pb2.Struct()
  phosphorus_input_properties['requests'] = {
      'gale_gale': {
          'params': {
              'decorations': {
                  'tags': [
                      'label-board:gale', 'analytics_name:RLZ',
                      'label-model:gale', 'build:gale-release/R89-13729.57.2',
                      'suite:rlz', 'ctp-fwd-task-name:RLZ',
                      'label-pool:MANAGED_POOL_QUOTA'
                  ]
              },
              'hardwareAttributes': {
                  'model': 'gale'
              },
              'metadata': {
                  'debugSymbolsArchiveUrl':
                      'gs://chromeos-image-archive/gale-release/R89-13729.57.2',
                  'testMetadataUrl':
                      'gs://chromeos-image-archive/gale-release/R89-13729.57.2'
              },
              'retry': {
                  'allow': True,
                  'max': 3
              },
              'scheduling': {
                  'managedPool': 'MANAGED_POOL_QUOTA',
                  'qsAccount': 'legacypool-suites'
              },
              'softwareAttributes': {
                  'buildTarget': {
                      'name': 'gale'
                  }
              },
              'softwareDependencies': [{
                  'chromeosBuild': 'gale-release/R89-13729.57.2'
              }],
              'time': {
                  'maximumDuration': '153000s'
              }
          },
          'testPlan': {
              'suite': [{
                  'name': 'rlz'
              }]
          }
      }
  }

  green_cft_builds = [
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
          input={'properties': cft_input_properties},
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
          input={'properties': cft_input_properties},
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
          input={'properties': cft_input_properties},
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
          input={'properties': cft_input_properties},
      ),
      build_pb2.Build(
          id=7891,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': cft_input_properties},
      ),
      build_pb2.Build(
          id=78912,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': cft_input_properties},
      ),
      build_pb2.Build(
          id=78913,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': cft_input_properties},
      ),
      build_pb2.Build(
          id=78914,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': cft_input_properties},
      ),
      build_pb2.Build(
          id=78915,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': cft_input_properties},
      )
  ]
  green_phosphorus_builds = [
      # This build should always be skipped since it was previously replayed.
      build_pb2.Build(
          id=1,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 5),
          status='SUCCESS',
          input={'properties': phosphorus_input_properties},
      ),
      build_pb2.Build(
          id=2,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 65),
          status='SUCCESS',
          input={'properties': phosphorus_input_properties},
      ),
      build_pb2.Build(
          id=3,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 15),
          status='SUCCESS',
          input={'properties': phosphorus_input_properties},
      ),
      build_pb2.Build(
          id=4,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 30),
          status='SUCCESS',
          input={'properties': phosphorus_input_properties},
      )
  ]
  previous_replayed_runs = [
      build_pb2.Build(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform_foo_env',
          }, tags=[
              bb_common.StringPair(key=REPLAYED_PROD_BUILD_ID_TAG, value='100')
          ]),
  ]

  yield api.test(
      'successful-run',
      api.properties(
          **{
              'ctp_replay_max_runtime': 70 * 60,
              'ctp_num_replay_builds': 3,
              'ctp_builder': 'cros_test_platform-foo_env',
              '$chromeos/skylab': {
                  'ctp_builder': 'cros_test_platform-foo_env'
              }
          }),
      api.buildbucket.simulated_search_results(
          green_cft_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_replayed_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
  )

  yield api.test(
      'successful-run-with-ratios',
      api.properties(
          **{
              'ctp_replay_max_runtime': 70 * 60,
              'ctp_num_replay_builds': 10,
              'ctp_builder': 'cros_test_platform-foo_env',
              '$chromeos/skylab': {
                  'ctp_builder': 'cros_test_platform-foo_env'
              }
          }),
      api.buildbucket.simulated_search_results(
          green_cft_builds + green_phosphorus_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_replayed_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
  )

  yield api.test(
      'successful-run-cft',
      api.properties(
          **{
              'ctp_replay_max_runtime': 70 * 60,
              'ctp_num_replay_builds': 3,
              'ctp_builder': 'cros_test_platform-dev',
              '$chromeos/skylab': {
                  'ctp_builder': 'cros_test_platform-dev'
              }
          }),
      api.buildbucket.simulated_search_results(
          green_cft_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_replayed_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
  )

  yield api.test(
      'ctp-prod-build-not-found',
      api.buildbucket.simulated_search_results(
          [],
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'ctp-build-not-found-matching-runtime-limit',
      api.properties(
          **{
              'ctp_replay_max_runtime': 60 * 10,
              'ctp_builder': 'cros_test_platform-foo_env',
          }),
      api.buildbucket.simulated_search_results(
          green_cft_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_replayed_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
      api.post_check(post_process.StepFailure, 'replay prod CTP run'),
      status='FAILURE',
  )
