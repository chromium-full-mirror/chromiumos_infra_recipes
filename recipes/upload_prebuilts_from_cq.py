# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Recipe that retrieves locations from google storage that the binpkgs are
uploaded to by the Chrome PUpr and updates *_CQ_BINHOST.conf files with
the locations.

See go/cros-faster-cq-by-ealier-binpkg for the detail.
'''

from typing import Optional

from google.protobuf import timestamp_pb2

from PB.chromite.api import binhost as binhost_pb
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'build_menu': 'build_menu',
    'build_plan': 'build_plan',
    'cros_infra_config': 'cros_infra_config',
    'cros_prebuilts': 'cros_prebuilts',
    'cros_source': 'cros_source',
    'depot_tools_gerrit': 'depot_tools/gerrit',
    'gerrit': 'gerrit',
    'step': 'recipe_engine/step',
}

PYTHON_VERSION_COMPATIBILITY = 'PY3'

GERRIT_TOPIC = 'chromeos-base/lacros-ash-atomic'
GERRIT_PROJECT = 'chromiumos/overlays/chromiumos-overlay'
GERRIT_HOST = 'chromium-review.googlesource.com'
GERRIT_HOST_URL = 'https://' + GERRIT_HOST

GIT_PUSH_MAX_RETRY_COUNT = 3
RETRIEVING_LAST_MERGED_CHANGE_MAX_RETRY_COUNT = 3


# Utility function to get the last merged change from Gerrit. This method does
# double check if the result is actually latest, by querying Gerrit.
def get_last_merged_change(api: RecipeApi):

  # Utility function to get the last merged change from Gerrit. The result
  # rarely not the true last merged change,, since it returns the last N
  # recently changed changes and the actual one might not be included in the
  # results.
  def _query(api: RecipeApi, merged_after: Optional[str] = None):
    with api.step.nest(f'query {GERRIT_HOST_URL}') as pres_gerrit_query:
      query = [
          ('topic', GERRIT_TOPIC),
          ('project', GERRIT_PROJECT),
          ('branch', 'main'),
          ('status', 'merged'),
      ]
      if merged_after:
        query.append(('mergedafter', merged_after))

      changes = api.depot_tools_gerrit.get_changes(GERRIT_HOST_URL, query,
                                                   o_params=['ALL_REVISIONS'])

      pres_gerrit_query.step_text = f'found {len(changes)} matching CLs'
      for change in changes:
        change_num = str(change['_number'])
        change_url = f'https://crrev.com/c/{change_num}'
        pres_gerrit_query.links[f'found CL {change_num}'] = change_url

    last_submitted_date = '0'
    last_change = None
    for change in changes:
      submitted_date = change.get('submitted', None)
      # Comparing as strings
      if submitted_date and submitted_date > last_submitted_date:
        last_submitted_date = submitted_date
        last_change = change

    return last_change

  candidate = _query(api)
  if candidate is None:
    return None

  loop_count = 0
  while True:
    # Try finding a better candidate of the last merge change just in case.
    # |candidate| may not contain the actual last one due to the limit
    # of the number of returned records.
    better_candidate = _query(api, candidate['submitted'])

    if better_candidate['id'] == candidate['id']:
      break

    # Limit the number of loop to prevent an infinite loop.
    loop_count += 1
    if loop_count >= RETRIEVING_LAST_MERGED_CHANGE_MAX_RETRY_COUNT:
      raise StepFailure('Unable to get the last merged change.')

    candidate = better_candidate

  return candidate


def RunSteps(api: RecipeApi):
  is_staging = api.build_menu.is_staging

  with api.step.nest('search the last merged uprev CL') as pres_search_cls:
    change = get_last_merged_change(api)

    if change is None:
      pres_search_cls.step_summary_text = 'Found no CL. Finishing.'
      return

    change_num = change['_number']
    pres_search_cls.step_summary_text = f'Found http://crrev.com/c/{change_num}'
    pres_search_cls.logs['change'] = str(change)

  with api.step.nest('search the prebuilts') as presentation:
    if not 'revisions' in change or len(change['revisions']) == 0:
      raise StepFailure('no revisions in the change')

    current_revision = change['current_revision']
    landed_patchset = change['revisions'][current_revision]['_number']

    prebuilt_entries = []
    build_targets = set()
    debug_prebuilts_log = ''

    # Traverse the patchsets in reverse order to get the latest one with
    # successful CQ.
    for patchset in reversed(range(1, landed_patchset)):
      with api.step.nest(f'patchset #{patchset}'):
        gerrit_change = GerritChange(
            host=GERRIT_HOST,
            project=GERRIT_PROJECT,
            change=change_num,
            patchset=patchset,
        )

        # On prod, check only the prod builders
        # On staging, check both prod and staging builders.
        bucket = None if is_staging else 'cq'
        builder = builder_common_pb2.BuilderID(project='chromeos',
                                               bucket=bucket)
        builds = api.buildbucket.search(
            builds_service_pb2.BuildPredicate(
                gerrit_changes=[gerrit_change],
                builder=builder,
                include_experimental=is_staging,
            ))

        sorted_builds = sorted(builds, key=lambda b: b.start_time.ToSeconds())
        for build in reversed(sorted_builds):
          # On prod, use only prebuilts from prod (ignoring staging prebuilts).
          # On staging, use prebuilts from both prod and staging.
          if not is_staging and build.builder.bucket != 'cq':
            continue

          # Ignore failed builds.
          if build.status != common_pb2.SUCCESS:
            continue

          build_target = api.cros_infra_config.get_build_target(build)
          build_target_name = build_target.name if build_target else 'None'
          prebuilts_uri = (
              build.output.properties['prebuilts_uri']
              if 'prebuilts_uri' in build.output.properties else None)
          prebuilts_private = (
              build.output.properties['prebuilts_private']
              if 'prebuilts_private' in build.output.properties else None)

          debug_prebuilts_log += (f'{build.id}: {build.builder.builder}: ' +
                                  f'{build_target_name}: ' +
                                  f'{prebuilts_uri} ({prebuilts_private})\n')

          # Ignore builds without uploaded prebuilt.
          if prebuilts_uri is None:
            continue

          # Skip if the newer (= former in the loop) entry of the same build
          # target exists.
          if build_target.name in build_targets:
            continue

          build_targets.add(build_target.name)
          prebuilt_entries.append({
              'build_target':
                  build_target,
              'build_end_time':
                  build.end_time,
              'prebuilts_private':
                  prebuilts_private if prebuilts_private is not None else True,
              'prebuilts_uri':
                  prebuilts_uri,
          })

        # If there is an entry, stop the traversal of the patchset.
        if len(prebuilt_entries) > 0:
          break

    presentation.logs['debug_prebuilts_log'] = debug_prebuilts_log
    presentation.logs['prebuilt_entries'] = str(prebuilt_entries)
    # Sorting to make the result stable among different Python versions.
    presentation.logs['build_targets'] = str(sorted(build_targets))

    if not prebuilt_entries:
      presentation.step_summary_text = (
          'Found no builds with uploaded prebuilts. Finishing.')
      return

    presentation.step_summary_text = (
        f'Found {len(prebuilt_entries)} builds with uploaded prebuilts.')

  with api.step.nest('set BINHOSTs'):
    api.cros_source.configure_builder(default_main=True)
    with api.cros_source.checkout_overlays_context(
    ), api.build_menu.setup_workspace(cherry_pick_changes=True):
      # TODO(b/277171567): Combine the CLs.
      for entry in prebuilt_entries:
        build_target = entry['build_target']
        with api.step.nest(f'update {build_target.name}') as presentation:
          api.cros_prebuilts.set_binhost(
              build_target,
              entry['prebuilts_private'],
              binhost_pb.CQ_BINHOST,
              entry['prebuilts_uri'],
              push_retries=GIT_PUSH_MAX_RETRY_COUNT,
          )


def GenTests(api: RecipeTestApi):

  # Utility method to generate an output prop.
  def gen_output_props(**kwargs):
    output = build_pb2.Build.Output()
    output.properties.update(kwargs)
    return output

  CHANGE = {
      'id':
          'chromiumos%2Foverlays%2Fchromiumos-overlay~main~I0123456789abcdef0123456789abcdef01234567',
      '_number':
          4567890,
      'host':
          GERRIT_HOST,
      'project':
          GERRIT_PROJECT,
      'current_revision':
          '0123456789abcdef0123456789abcdef01234567',
      'revisions': {
          '2222222222222222222222222222222222222222': {
              '_number': 2,
          },
          '0123456789abcdef0123456789abcdef01234567': {
              '_number': 3,
          }
      },
      'submitted':
          '2023-01-01 00:00:00.000000000',
  }

  NEWER_CHANGE1 = {
      'id':
          'chromiumos%2Foverlays%2Fchromiumos-overlay~main~Ixxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      '_number':
          4567891,
      'submitted':
          '2023-01-02 00:00:00.000000000',
  }

  NEWER_CHANGE2 = {
      'id':
          'chromiumos%2Foverlays%2Fchromiumos-overlay~main~Iyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy',
      '_number':
          4567892,
      'submitted':
          '2023-01-03 00:00:00.000000000',
  }

  NEWER_CHANGE3 = {
      'id':
          'chromiumos%2Foverlays%2Fchromiumos-overlay~main~Izzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz',
      '_number':
          4567893,
      'submitted':
          '2023-01-04 00:00:00.000000000',
  }

  BUILDS = [
      # Completed successfully on amd64-generic (staging).
      build_pb2.Build(
          id=8922054662172514000,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338800),
          builder={
              'builder': 'staging-amd64-generic-cq',
              'bucket': 'staging',
          },
      ),
      # Completed successfully on amd64-generic (prod).
      build_pb2.Build(
          id=8922054662172514001,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338801),
          builder={
              'builder': 'amd64-generic-cq',
              'bucket': 'cq'
          },
      ),
      # Completed successfully on betty (staging).
      build_pb2.Build(
          id=8922054662172514002,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'betty-pi-arc'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338802),
          builder={
              'builder': 'staging-betty-pi-arc-cq',
              'bucket': 'staging'
          },
      ),
      # Completed successfully on betty (prod).
      build_pb2.Build(
          id=8922054662172514003,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'betty-pi-arc'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338803),
          builder={
              'builder': 'betty-pi-arc-cq',
              'bucket': 'cq'
          },
      ),
      # Another run of amd64-generic.
      build_pb2.Build(
          id=8922054662172514007,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338807),
          builder={
              'builder': 'amd64-generic-cq',
              'bucket': 'cq'
          },
      ),
      # Failed run of arm64-generic.
      build_pb2.Build(
          id=8922054662172514008,
          status=common_pb2.FAILURE,
          input=api.build_plan.input_proto(None, 'arm64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338808),
          builder={
              'builder': 'arm64-generic-cq',
              'bucket': 'cq'
          },
      ),
      # Succeeded but not uploaded prebuilts.
      build_pb2.Build(
          id=8922054662172514009,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          create_time=timestamp_pb2.Timestamp(seconds=1598338809),
          builder={
              'builder': 'amd64-generic-cq',
              'bucket': 'cq'
          },
      ),
  ]

  yield api.build_menu.test(
      'no-uprev-cls',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [], GERRIT_HOST_URL, 1),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs'),
  )

  yield api.build_menu.test(
      'inconsistent-gerrit-response',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response(
          'search the last merged uprev CL',
          [NEWER_CHANGE1],
          GERRIT_HOST_URL,
          2,
      ),
      api.gerrit.set_query_changes_response(
          'search the last merged uprev CL',
          [NEWER_CHANGE2],
          GERRIT_HOST_URL,
          3,
      ),
      api.gerrit.set_query_changes_response(
          'search the last merged uprev CL',
          [NEWER_CHANGE3],
          GERRIT_HOST_URL,
          4,
      ),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs'),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'invalid-gerrit-response',
      api.gerrit.set_query_changes_response(
          'search the last merged uprev CL',
          [NEWER_CHANGE1],
          GERRIT_HOST_URL,
          1,
      ),
      api.gerrit.set_query_changes_response(
          'search the last merged uprev CL',
          [NEWER_CHANGE1],
          GERRIT_HOST_URL,
          2,
      ),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs'),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'no-buildbucket-results',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          [],
          step_name='search the prebuilts.patchset #2.buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          [],
          step_name='search the prebuilts.patchset #1.buildbucket.search',
      ),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs'),
  )

  yield api.build_menu.test(
      'build-buckets-results',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the prebuilts.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
  )

  yield api.build_menu.test(
      'build-buckets-results-staging',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the prebuilts.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
      bucket='staging')
