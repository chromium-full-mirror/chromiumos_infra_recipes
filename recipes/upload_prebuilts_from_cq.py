# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Recipe that retrieves locations from google storage that the binpkgs are
uploaded to by the Chrome PUpr and updates *_CQ_BINHOST.conf files with
the locations.

See go/cros-faster-cq-by-ealier-binpkg for the detail.
'''

import time

from typing import List, Optional, Set, Tuple

from google.protobuf import timestamp_pb2

from PB.recipe_engine.result import RawResult
from PB.chromite.api import binhost as binhost_pb
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from PB.recipes.chromeos.upload_prebuilts_from_cq import (
    UploadPrebuiltsFromCqProperties)

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
    'properties': 'recipe_engine/properties',
    'step': 'recipe_engine/step',
    'time': 'recipe_engine/time',
}

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UploadPrebuiltsFromCqProperties

GERRIT_TOPIC = 'chromeos-base/lacros-ash-atomic'
GERRIT_PROJECT = 'chromiumos/overlays/chromiumos-overlay'
GERRIT_HOST = 'chromium-review.googlesource.com'
GERRIT_HOST_URL = 'https://' + GERRIT_HOST

GIT_PUSH_MAX_RETRY_COUNT = 3
RETRIEVING_LAST_MERGED_CHANGE_MAX_RETRY_COUNT = 3

TIMEOUT_SEC = 5 * 60 * 60


def get_last_merged_change(api: RecipeApi) -> Optional[GerritChange]:
  """Utility function to get the last merged change from Gerrit.

  This method does double check if the result is actually latest, by querying
  Gerrit.

  Args:
    api: See RunSteps documentation.

  Returns:
    GerritChange of the last marged uprev. Or None if not found.
  """

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


def get_buildbucket_builds(api: RecipeApi, gerrit_change: GerritChange,
                           is_staging: bool) -> List[build_pb2.Build]:
  """Utility function to get the builds corresponding to the gerrit change.

  Args:
    api: See RunSteps documentation.
    gerrit_change: The gerrit changes to get the corresponding builds to.
    is_staging: True if wants the results from the staging environment.

  Returns:
    Builds of the gerrit change.
  """

  builder = builder_common_pb2.BuilderID(project='chromeos')
  builds = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(
          gerrit_changes=[gerrit_change],
          builder=builder,
          include_experimental=is_staging,
      ), limit=500)

  # Extract only the build builders so that we don't need to wait for the end
  # of the test builder executions.
  return list(
      filter(
          lambda x:
          # Remove the test builders.
          x.builder.bucket not in ['test_runner', 'testplatform', 'vmtest'] and
          # Remove the cq-orchestrator.
          x.builder.bucket not in
          ['cq-orchestrator', 'staging-cq-orchestrator'] and
          # On prod, use only prebuilts from prod.
          # On staging, use prebuilts from both prod and staging.
          (is_staging or x.builder.bucket != 'staging'),
          builds))


def search_prebuilts(api: RecipeApi, step_name: str,
                     fetched_builds: Optional[List[build_pb2.Build]],
                     gerrit_change: GerritChange,
                     finished_build_targets: Set[str],
                     is_staging: bool) -> Tuple[List[dict], List[str]]:
  """Utility function to get the prebuilts corresponding to the gerrit change.

  Args:
    api: See RunSteps documentation.
    step_name: Name of the step of this process to be shown in the Luci UI.
    fetched_builds: Builds corresponding to |gerrit_change|. If None, the
        method fetches the latest result.
    gerrit_change: The gerrit changes to get the corresponding prebuilts to.
    finished_build_targets: Set of the finished build names. Builders in the
        set are processed. The processed builders are added to this set.
    is_staging: True if wants the results from the staging environment.

  Returns:
    Tuple of the following 2 values:
    - List of prebuilt entries that are added in this method
    - List of names of running builders
  """

  build_targets = set()
  debug_prebuilts_log = ''
  prebuilt_entries = []
  running_builds = []

  with api.step.nest(step_name) as presentation:
    builds = (
        fetched_builds or
        get_buildbucket_builds(api, gerrit_change, is_staging))

    sorted_builds = sorted(builds, key=lambda b: b.start_time.ToSeconds())
    for build in reversed(sorted_builds):
      build_target = api.cros_infra_config.get_build_target(build)
      build_target_name = build_target.name if build_target else 'None'
      prebuilts_uri = (
          build.output.properties['prebuilts_uri']
          if 'prebuilts_uri' in build.output.properties else None)
      prebuilts_private = (
          build.output.properties['prebuilts_private']
          if 'prebuilts_private' in build.output.properties else None)

      continue_reason = []

      # Ignore target-less builds.
      if build_target is None:
        continue_reason.append('The build target is none')

      # Ignore running builders.
      if (build.status & common_pb2.ENDED_MASK) == 0:
        running_builds.append(build_target_name)
        continue_reason.append('The builder is not finished yet.')

      # Ignore failed builds.
      if build.status != common_pb2.SUCCESS:
        continue_reason.append('The builder has failed.')

      # Ignore builds without uploaded prebuilt.
      if prebuilts_uri is None:
        continue_reason.append('The builder did not uploaded its prebuilt.')

      # Skip if the newer (= former in the loop) entry of the same build
      # target exists.
      if build_target_name != 'None' and build_target_name in finished_build_targets:
        continue_reason.append('The prebuilt  alderady uploaded.')

      # LF ('\n') is not added here, but added later with the result.
      debug_prebuilts_log += (f'{build.id}: {build.builder.builder}: ' +
                              f'{build_target_name}: ' +
                              f'{prebuilts_uri} ({prebuilts_private}): ')

      if len(continue_reason) > 0:
        reasons = ', '.join(continue_reason)
        debug_prebuilts_log += f'=> Skipped ({reasons})\n'
        continue

      debug_prebuilts_log += '=> Uploading prebuilts\n'

      build_targets.add(build_target.name)
      finished_build_targets.add(build_target.name)

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

    presentation.logs['debug_prebuilts_log'] = debug_prebuilts_log
    presentation.logs['prebuilt_entries'] = str(prebuilt_entries)
    # Sorting to make the result stable among different Python versions.
    presentation.logs['build_targets'] = str(sorted(build_targets))
    presentation.logs['running_builds'] = str(running_builds)

    sorted_builds_len = len(sorted_builds)
    prebiously_updated_builds_len = (
        len(finished_build_targets) - len(build_targets))
    prebuilt_entries_len = len(prebuilt_entries)
    running_builds_len = len(running_builds)
    presentation.step_summary_text = (
        f'Total {sorted_builds_len} builds:\n'
        f'- {prebiously_updated_builds_len} previously-updated builds\n'
        f'- {prebuilt_entries_len} succeeded builds with uploaded prebuilts\n'
        f'- {running_builds_len} running builds\n')

  return prebuilt_entries, running_builds


def set_binhots(api: RecipeApi, step_name: str, prebuilt_entries: List[dict]):
  """Utility function to set the binhosts repeatedly.

  Args:
    api: See RunSteps documentation.
    step_name: Name of the step of this process to be shown in the Luci UI.
    prebuilt_entries: Prebuilts to be set the binhosts of.
  """

  with api.step.nest(step_name) as presentation:
    prebuilt_entries_len = len(prebuilt_entries)
    presentation.step_summary_text = f'Set {prebuilt_entries_len} builds'
    with api.cros_source.checkout_overlays_context(
    ), api.build_menu.setup_workspace(cherry_pick_changes=True):
      # TODO(b/277171567): Combine the CLs.
      for entry in prebuilt_entries:
        build_target = entry['build_target']
        with api.step.nest(f'update {build_target.name}'):
          api.cros_prebuilts.set_binhost(
              build_target,
              entry['prebuilts_private'],
              binhost_pb.CQ_BINHOST,
              entry['prebuilts_uri'],
              push_retries=GIT_PUSH_MAX_RETRY_COUNT,
          )


def RunSteps(api: RecipeApi, properties: UploadPrebuiltsFromCqProperties):
  timeout_sec = properties.timeout_sec or TIMEOUT_SEC

  summary = DoRunSteps(api, timeout_sec) or ''
  return RawResult(status=common_pb2.SUCCESS, summary_markdown=summary)


def DoRunSteps(api: RecipeApi, entire_timeout_sec: int) -> Optional[str]:
  is_staging = api.build_menu.is_staging
  start_time = time.time()

  with api.step.nest('search the last merged uprev CL') as pres_search_cls:
    change = get_last_merged_change(api)

    if change is None:
      pres_search_cls.step_summary_text = 'Found no CL. Finishing.'
      return 'Found no CL'

    change_num = change['_number']
    pres_search_cls.step_summary_text = \
        f'Found http://crrev.com/c/{change_num}'
    pres_search_cls.logs['change'] = str(change)

  with api.step.nest('search the patchset') as presentation:
    if not 'revisions' in change or len(change['revisions']) == 0:
      raise StepFailure('no revisions in the change')

    current_revision = change['current_revision']
    landed_patchset = change['revisions'][current_revision]['_number']

    prebuilt_entries = []
    builds = []

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

        builds = get_buildbucket_builds(api, gerrit_change, is_staging)
        if len(builds) > 0:
          presentation.step_summary_text = f'Choose the patchset #{patchset}'
          break

    if len(builds) == 0:
      presentation.step_summary_text = 'No patchset found. Exiting'
      return 'No patchset found on the last uprev CL'

  # Require to manipulate the reposity (setting BINHOSTS).
  api.cros_source.configure_builder(default_main=True)

  # Parameters for the exponential-backoff retries.
  INITIAL_TIMEOUT_SEC = 2 * 60
  MAXIMUM_TIMEOUT_SEC = 30 * 60
  MULTIPLIER_ON_NOT_FOUND = 2

  finished_build_targets = set()
  timeout = INITIAL_TIMEOUT_SEC
  count = 1
  while True:
    name_suffix = "" if count == 1 else f" ({count})"
    prebuilt_entries, running_builds = search_prebuilts(
        api, 'search the prebuilts' + name_suffix, builds, gerrit_change,
        finished_build_targets, is_staging)
    # Set None for 2nd runs and later to retrieve the latest builds.
    builds = None

    if len(prebuilt_entries) > 0:
      # If any builder finishes, set their binhosts.
      set_binhots(api, 'set BINHOSTs' + name_suffix, prebuilt_entries)
    else:
      # Waiting with an exponential backoff algorithm if no builder finishes.
      timeout = min(timeout * MULTIPLIER_ON_NOT_FOUND, MAXIMUM_TIMEOUT_SEC)

    running_builds_len = len(running_builds)
    if running_builds_len == 0:
      # There are no running builders to wait for. Finishes the task.
      break

    finished_build_targets_len = len(finished_build_targets)
    all_builds_len = len(finished_build_targets) + running_builds_len

    # Adding one sec is a hack for test.
    if (time.time() - start_time + 1) >= entire_timeout_sec:
      return "\n".join([
          f"Updated {finished_build_targets_len} of {all_builds_len} builders after {count} trials.",
          f"Interrupted: maximum running time ({entire_timeout_sec} sec) exceeded.",
      ])

    with api.step.nest(f'waiting {timeout} sec for next retry') as presentation:
      presentation.step_summary_text = \
          f'{running_builds_len} of {all_builds_len} builds still running.'
      api.m.time.sleep(timeout)

    count += 1

  finished_build_targets_len = len(finished_build_targets)
  return f"Updated all of {finished_build_targets_len} builders after {count} trials."


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

  # Finished state of builder list: the all builds are finished.
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

  # Intermediate state of builder list: containing running and finished builds.
  BUILDS_INTERMEDIATE = [
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
      # Completed successfully on betty (prod).
      build_pb2.Build(
          id=8922054662172514003,
          status=common_pb2.STARTED,
          input=api.build_plan.input_proto(None, 'betty-pi-arc'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338803),
          builder={
              'builder': 'betty-pi-arc-cq',
              'bucket': 'cq'
          },
      ),
  ]

  # List that contains no prod builders.
  BUILDS_STAGING = [
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
  ]

  # List that contains no prod builders.
  BUILDS_INVALID = [
      # Completed successfully on amd64-generic (staging).
      build_pb2.Build(
          id=8922054662172514000,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338800),
          builder={
              'builder': 'amd64-generic-cq',
              'bucket': 'cq',
          },
      ),
      # Completed successfully on amd64-generic (staging).
      build_pb2.Build(
          id=8922054662172514001,
          status=common_pb2.SUCCESS,
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338800),
      ),
  ]

  yield api.build_menu.test(
      'no-uprev-cls',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [], GERRIT_HOST_URL, 1),
      api.post_check(post_process.DoesNotRun, 'search the patchset'),
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
      api.post_check(post_process.DoesNotRun, 'search the patchset'),
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
      api.post_check(post_process.MustRun, 'search the patchset'),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
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
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          [],
          step_name='search the patchset.patchset #1.buildbucket.search',
      ),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs'),
  )

  yield api.build_menu.test(
      'no-sufficient-buildbucket-results',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS_STAGING,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
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
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 2 builders after 1 trials.'),
  )

  yield api.build_menu.test(
      'build-buckets-results-staging',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 2 builders after 1 trials.'),
      bucket='staging',
  )

  yield api.build_menu.test(
      'contains-pending-builder',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS_INTERMEDIATE,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the prebuilts (2).buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
      api.post_check(post_process.MustRun, 'waiting 120 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs (2).update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs (2).update brya'),
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 2 builders after 2 trials.'),
  )

  yield api.build_menu.test(
      'contains-pending-builder2',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS_INTERMEDIATE,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          BUILDS_INTERMEDIATE,
          step_name='search the prebuilts (2).buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the prebuilts (3).buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs.update brya'),
      api.post_check(post_process.MustRun, 'waiting 120 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs (2).update brya'),
      api.post_check(post_process.MustRun, 'waiting 240 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (3).update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs (3).update betty-pi-arc'),
      api.post_check(post_process.DoesNotRun, 'set BINHOSTs (3).update brya'),
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 2 builders after 3 trials.'),
  )

  yield api.build_menu.test(
      'contains-targetless-build',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS_INVALID,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 1 builders after 1 trials.'),
  )

  yield api.build_menu.test(
      'exceeded-timeout',
      api.properties(timeout_sec=1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS_INTERMEDIATE,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'set BINHOSTs.update amd64-generic'),
      api.post_check(
          post_process.SummaryMarkdown,
          'Updated 1 of 2 builders after 1 trials.\nInterrupted: maximum running time (1 sec) exceeded.'
      ),
  )
