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
    'cros_infra_config',
    'cros_test_platform',
    'skylab',
]

DEFAULT_CTP_REPLAY_MAX_RUNTIME = 90 * 60  # 90 minutes
CTP_BUILDS_TO_REPLAY = 10
MAX_CTP1_RATIO = 0.7
REPLAYED_PROD_BUILD_ID_TAG = 'replay_from_prod_buildbucket_id'
POOL_TAG_PREFIX = 'label-pool:'


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
                                         time_limit_seconds,
                                         num_builds=CTP_BUILDS_TO_REPLAY):
  # Only search up to 6 hrs back to make sure we replay relevant prod CTP data.
  six_hours_back = _bb_time_range(api, 12 * 60)
  ctp_prod_builder = 'cros_test_platform'
  successful_prod_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': ctp_prod_builder,
          }, status=bb_common.SUCCESS, create_time=six_hours_back),
      fields=['id', 'start_time', 'end_time', 'tags', 'input'], limit=1000,
      step_name='find recent green %s builds' % ctp_prod_builder)
  if not successful_prod_builds:
    raise api.step.StepFailure('No successful builds found for builder %s' %
                               ctp_prod_builder)

  already_replayed_build_ids = _already_replayed_ctp_build_ids(
      api, replay_builder, six_hours_back)

  ctp2_pools = []
  try:
    with api.step.nest('get allowed pools for ctpv2') as step:
      ctp2_pools = api.cros_infra_config.get_ctp2_pools_config()
      step.logs['allowed pools'] = '\n'.join(ctp2_pools)
  # pylint: disable=broad-except
  except Exception:  # pragma: no cover
    pass

  max_ctp1_builds = int(num_builds * MAX_CTP1_RATIO)
  ctp1_builds = []
  ctp2_builds = []

  for build in successful_prod_builds:
    run_time = build.end_time.seconds - build.start_time.seconds
    # Only use builds with runtime less than time_limit_seconds.
    if run_time > time_limit_seconds or build.id in already_replayed_build_ids:
      continue

    if _is_ctp2_build(build, ctp2_pools):
      ctp2_builds.append(build)
    elif len(ctp1_builds) < max_ctp1_builds:
      ctp1_builds.append(build)

    # Don't stop scanning builds until the total max and the CTPv1 max are met.
    if (len(ctp1_builds) + len(ctp2_builds) >= num_builds and
        len(ctp1_builds) >= max_ctp1_builds):
      break

  if not ctp1_builds and not ctp2_builds:
    raise api.step.StepFailure(
        'No new successful builds with completion time under {}s found for builder {}'
        .format(time_limit_seconds, ctp_prod_builder))

  max_ctp2_builds = num_builds - len(ctp1_builds)
  ctp2_builds_to_return = min(len(ctp2_builds), max_ctp2_builds)
  return ctp1_builds + ctp2_builds[:ctp2_builds_to_return]


def _is_ctp2_build(build, ctp2_pools):
  for req in MessageToDict(build.input.properties['requests']).values():
    params = req.get('params')
    if not params:
      continue  # pragma: no cover
    decorations = params.get('decorations')
    if not decorations:
      continue  # pragma: no cover
    tags = decorations.get('tags')
    if not tags:
      continue  # pragma: no cover
    for tag in tags:
      if not tag.startswith(POOL_TAG_PREFIX):
        continue
      pool = tag.removeprefix(POOL_TAG_PREFIX)
      if pool in ctp2_pools:
        return True

  return False


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
  ctp1_input_properties = struct_pb2.Struct()
  ctp1_input_properties['requests'] = {
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

  ctp2_input_properties = struct_pb2.Struct()
  ctp2_input_properties['requests'] = {
      'gale_gale': {
          'params': {
              'decorations': {
                  'tags': [
                      'label-board:gale', 'analytics_name:RLZ',
                      'label-model:gale', 'build:gale-release/R89-13729.57.2',
                      'suite:rlz', 'ctp-fwd-task-name:RLZ',
                      'label-pool:schedukeTest'
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

  green_ctp1_builds = [
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
          input={'properties': ctp1_input_properties},
      ),
      build_pb2.Build(
          id=123,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 95),
          status='SUCCESS',
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
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
          input={'properties': ctp1_input_properties},
      )
  ]
  green_ctp2_builds = [
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
          input={'properties': ctp2_input_properties},
      ),
      build_pb2.Build(
          id=2,
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          start_time=timestamp_pb2.Timestamp(seconds=1617230018),
          end_time=timestamp_pb2.Timestamp(seconds=1617230018 + 60 * 95),
          status='SUCCESS',
          input={'properties': ctp2_input_properties},
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
          input={'properties': ctp2_input_properties},
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
          input={'properties': ctp2_input_properties},
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
          green_ctp1_builds,
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
          green_ctp1_builds + green_ctp2_builds,
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
              'ctp_replay_max_runtime': 100 * 60,
              'ctp_num_replay_builds': 3,
              'ctp_builder': 'cros_test_platform-dev',
              '$chromeos/skylab': {
                  'ctp_builder': 'cros_test_platform-dev'
              }
          }),
      api.buildbucket.simulated_search_results(
          green_ctp1_builds,
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
          green_ctp1_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform builds'
      ),
      api.buildbucket.simulated_search_results(
          previous_replayed_runs,
          step_name='replay prod CTP run.filter out already-replayed builds'),
      api.post_check(post_process.StepFailure, 'replay prod CTP run'),
      status='FAILURE',
  )
