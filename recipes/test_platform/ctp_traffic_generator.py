# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that triggers ctp-{dev/staging}-traffic-generator runs.
"""

from google.protobuf import timestamp_pb2
from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.test_platform.ctp_traffic_generator import Properties

PROPERTIES = Properties
DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_test_platform',
    'skylab',
]

_CTP1_LIVE_COUNT = 7
_CTP2_LIVE_COUNT = 3
_DDD_DRY_RUN_COUNT = 5

_LIVE_REPLAY_MAX_RUNTIME = 90 * 60  # 90 minutes
_REPLAYED_PROD_BUILD_ID_TAG = 'replay_from_prod_buildbucket_id'
_POOL_TAG_PREFIX = 'label-pool:'


def RunSteps(api, properties):  # pragma: no cover
  time_range = _bb_time_range(api, hours_back=12)
  prod_builds = _get_prod_builds(api, time_range, properties.ctp_builder)
  ctp2_pools = _get_ctp2_pools(api)

  # Replay a mix of CTP1 and CTP2 builds on live DUTs.
  ctp1_live_builds = _short_builds_to_live_replay(prod_builds, _CTP1_LIVE_COUNT,
                                                  ctp2_pools, replay_ctp2=False)
  ctp2_live_builds = _short_builds_to_live_replay(prod_builds, _CTP2_LIVE_COUNT,
                                                  ctp2_pools, replay_ctp2=True)
  _replay_builds(api, properties.ctp_builder,
                 ctp1_live_builds + ctp2_live_builds)

  if 'staging' in properties.ctp_builder:
    # Replay 3D builds in dry-run mode.
    ddd_dry_run_builds = _ddd_builds_to_dry_run_replay(prod_builds,
                                                       _DDD_DRY_RUN_COUNT)
    _replay_builds(api, properties.ctp_builder, ddd_dry_run_builds,
                   dry_run=True)


def _bb_time_range(api, hours_back):  # pragma: no cover
  current_timestamp_seconds = api.buildbucket.build.start_time.ToSeconds()
  return bb_common.TimeRange(
      start_time=timestamp_pb2.Timestamp(seconds=current_timestamp_seconds -
                                         60 * 60 * hours_back),
      end_time=timestamp_pb2.Timestamp(seconds=current_timestamp_seconds))


def _get_prod_builds(api, time_range, replay_builder):  # pragma: no cover
  ctp_prod_builder = 'cros_test_platform'
  unfiltered_prod_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': ctp_prod_builder,
          }, status=bb_common.SUCCESS, create_time=time_range),
      fields=['id', 'start_time', 'end_time', 'tags', 'input'], limit=1000,
      step_name='find recent green %s builds' % ctp_prod_builder)

  already_replayed_prod_build_ids = _already_replayed_prod_build_ids(
      api, replay_builder, time_range)

  prod_builds = []
  for build in unfiltered_prod_builds:
    if build.id not in already_replayed_prod_build_ids:
      prod_builds.append(build)

  if not prod_builds:
    raise api.step.StepFailure('No successful builds found for builder %s' %
                               ctp_prod_builder)
  return prod_builds


def _get_ctp2_pools(api):  # pragma: no cover
  ctp2_pools = []
  try:
    with api.step.nest('get allowed pools for ctpv2') as step:
      ctp2_pools = api.cros_infra_config.get_ctp2_pools_config()
      step.logs['allowed pools'] = '\n'.join(ctp2_pools)
    # pylint: disable=broad-except
  except Exception:
    pass
  return ctp2_pools


def _already_replayed_prod_build_ids(api, replay_builder,
                                     time_range):  # pragma: no cover
  ctp_builds_in_replay_builder = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': replay_builder,
          }, create_time=time_range), fields=['tags'],
      step_name='filter out already-replayed builds')

  replayed_prod_build_ids = set()
  for build in ctp_builds_in_replay_builder:
    for tag in build.tags:
      if tag.key == _REPLAYED_PROD_BUILD_ID_TAG:
        replayed_prod_build_ids.add(int(tag.value))
        break
  return replayed_prod_build_ids


def _short_builds_to_live_replay(prod_builds, count, ctp2_pools,
                                 replay_ctp2):  # pragma: no cover
  if count <= 0:
    return []

  short_builds = []
  for build in prod_builds:
    # Only replay live builds that ran relatively quickly.
    runtime = build.end_time.seconds - build.start_time.seconds
    if runtime > _LIVE_REPLAY_MAX_RUNTIME:
      continue

    is_ctp2 = _is_ctp2_build(build, ctp2_pools)
    if (is_ctp2 and not replay_ctp2) or (not is_ctp2 and replay_ctp2):
      continue
    short_builds.append(build)
    if len(short_builds) >= count:
      break

  return short_builds


def _ddd_builds_to_dry_run_replay(prod_builds, count):  # pragma: no cover
  if count <= 0:
    return []

  ddd_builds = []
  for build in prod_builds:
    # Only replay 3D builds.
    if not _is_ddd_build(build):
      continue
    ddd_builds.append(build)
    if len(ddd_builds) >= count:
      break

  return ddd_builds


def _is_ctp2_build(build, ctp2_pools):  # pragma: no cover
  for req in MessageToDict(build.input.properties['requests']).values():
    params = req.get('params')
    if not params:
      continue
    decorations = params.get('decorations')
    if not decorations:
      continue
    tags = decorations.get('tags')
    if not tags:
      continue
    for tag in tags:
      if not tag.startswith(_POOL_TAG_PREFIX):
        continue
      pool = tag.removeprefix(_POOL_TAG_PREFIX)
      if pool in ctp2_pools:
        return True

  return False


def _is_ddd_build(build):  # pragma: no cover
  for req in MessageToDict(build.input.properties['requests']).values():
    params = req.get('params')
    if not params:
      continue
    if params.get('dddSuite') and params.get('runViaCft'):
      return True

  return False


def _replay_builds(api, replay_builder, builds,
                   dry_run=False):  # pragma: no cover
  for build in builds:
    reqs = MessageToDict(build.input.properties['requests'])
    new_reqs = _modify_reqs_for_replay(replay_builder, reqs, dry_run)
    if not new_reqs:
      continue
    bb_tags = {
        _REPLAYED_PROD_BUILD_ID_TAG: str(build.id),
        'parent_buildbucket_id': str(api.buildbucket.build.id)
    }
    api.skylab.schedule_ctp_requests(tagged_requests=reqs, bb_tags=bb_tags)


def _modify_reqs_for_replay(replay_builder, reqs_dict,
                            dry_run):  # pragma: no cover
  # TODO(b/267268890): Remove after TRv2 rolls to prod.
  dev = 'dev' in replay_builder
  if not dev and not dry_run:
    return reqs_dict

  new_reqs_dict = {}
  for tag, req in reqs_dict.items():
    if not req.get('params'):
      continue

    if dry_run:
      req['params']['dryRunCtpv2'] = True

    # TODO(b/267268890): Remove after TRv2 rolls to prod.
    if dev and req['params'].get('runViaCft'):
      # Run the request in trv2
      req['params']['runViaTrv2'] = True
      new_reqs_dict[tag] = req

  return new_reqs_dict


def GenTests(api):
  yield api.test('basic', api.properties(), status='FAILURE')
