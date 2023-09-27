# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that retrieves locations from google storage that the binpkgs are
uploaded to by the Chrome PUpr and updates *_CQ_BINHOST.conf files with
the locations.

See go/cros-faster-cq-by-ealier-binpkg for the detail.
"""

import time

from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

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
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)

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
    'cros_build_api': 'cros_build_api',
    'cros_infra_config': 'cros_infra_config',
    'cros_prebuilts': 'cros_prebuilts',
    'cros_source': 'cros_source',
    'depot_tools_gerrit': 'depot_tools/gerrit',
    'gerrit': 'gerrit',
    'properties': 'recipe_engine/properties',
    'scheduler': 'recipe_engine/scheduler',
    'step': 'recipe_engine/step',
    'time': 'recipe_engine/time',
    'workspace_util': 'workspace_util',
}

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UploadPrebuiltsFromCqProperties

GERRIT_TOPIC = 'chromeos-base/lacros-ash-atomic'
GERRIT_HOST = 'chromium-review.googlesource.com'
GERRIT_HOST_URL = 'https://' + GERRIT_HOST

PUBLIC_OVERLAY_PROJECT = 'chromiumos/overlays/chromiumos-overlay'
PRIVATE_OVERLAY_PROJECT = 'chromeos/overlays/chromeos-partner-overlay'
BINHOST_PROJECTS = [PUBLIC_OVERLAY_PROJECT, PRIVATE_OVERLAY_PROJECT]

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
          ('project', PUBLIC_OVERLAY_PROJECT),
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


def search_prebuilts(
    api: RecipeApi, step_name: str,
    fetched_builds: Optional[List[build_pb2.Build]],
    gerrit_change: GerritChange, finished_builds: Dict[str, Set[str]],
    is_staging: bool) -> Tuple[List[dict], List[dict], List[str]]:
  """Utility function to get the prebuilts corresponding to the gerrit change.

  Args:
    api: See RunSteps documentation.
    step_name: Name of the step of this process to be shown in the Luci UI.
    fetched_builds: Builds corresponding to |gerrit_change|. If None, the
        method fetches the latest result.
    gerrit_change: The gerrit changes to get the corresponding prebuilts to.
    finished_builds: Dict to store the build_target and profiles of the
        finished builds. See the comment in `update_prebuilts()` for details.
    is_staging: True if wants the results from the staging environment.

  Returns:
    Tuple of the following 2 values:
    - List of public prebuilt entries added in this method
    - List of private prebuilt entries added in this method
    - List of names of running builders
  """

  build_targets = defaultdict(set)
  debug_prebuilts_log = ''
  public_prebuilt_entries = []
  private_prebuilt_entries = []
  running_builds = []

  with api.step.nest(step_name) as presentation:
    builds = (
        fetched_builds or
        get_buildbucket_builds(api, gerrit_change, is_staging))

    sorted_builds = sorted(builds, key=lambda b: b.start_time.ToSeconds())
    for build in reversed(sorted_builds):
      build_target = api.cros_infra_config.get_build_target(build)
      build_target_name = build_target.name if build_target else 'None'
      builder_name = build.builder.builder
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
        running_builds.append(builder_name)
        continue_reason.append('The builder is not finished yet.')

      # Ignore failed builds.
      if build.status != common_pb2.SUCCESS:
        continue_reason.append('The builder has failed.')

      # Ignore builds without uploaded prebuilt.
      if prebuilts_uri is None:
        continue_reason.append('The builder did not upload prebuilts.')

      # The builder config retrieved here might have been updated since the
      # original build ran. It should be rare that the profile is changed, so
      # that we use the retrieved configuration here.
      # TODO(b/291943391): make the builders pass the used profile.
      builder_config = api.cros_infra_config.get_builder_config(
          builder_name, missing_ok=True)

      if not builder_config:
        profile_name = '(no builder configuration)'
        # Carry on if the builder doesn't exist anymore.
        continue_reason.append(
            f'The builder configration for {builder_name} does not exist.')
      else:
        profile_name = builder_config.build.portage_profile.profile
        if profile_name != '' and not is_staging:
          continue_reason.append(
              'Non-default profile is allowed only on staging.')

        # Skip if the newer (= former in the loop) entry of the same build
        # target exists.
        if build_target_name != 'None' and builder_name in finished_builds.get(
            build_target_name, {}):
          continue_reason.append('The prebuilts are already uploaded.')

      # LF ('\n') is not added here, but added later with the result.
      debug_prebuilts_log += (f'{build.id}: {builder_name}: ' +
                              f'{build_target_name}: ' + f'{profile_name}: ' +
                              f'{prebuilts_uri} ({prebuilts_private}): ')

      if continue_reason:
        reasons = ' / '.join(continue_reason)
        debug_prebuilts_log += f'=> Skipped ({reasons})\n'
        continue

      debug_prebuilts_log += '=> Uploading prebuilts\n'

      build_targets[build_target_name].add(builder_name)
      finished_builds[build_target_name].add(builder_name)

      is_private = prebuilts_private if prebuilts_private is not None else True

      entry = {
          'build_target': build_target,
          'prebuilts_private': is_private,
          'prebuilts_uri': prebuilts_uri,
          # not used but for debugging.
          'build_profile': profile_name,
          # not used but for debugging.
          'builder_name': builder_name,
      }

      if entry['prebuilts_private']:
        private_prebuilt_entries.append(entry)
      else:
        public_prebuilt_entries.append(entry)

    presentation.logs['debug_prebuilts_log'] = debug_prebuilts_log
    presentation.logs['private_prebuilt_entries'] = str(
        private_prebuilt_entries)
    presentation.logs['public_prebuilt_entries'] = str(public_prebuilt_entries)
    presentation.logs['running_builds'] = str(running_builds)
    # Sorting to make the result fixed because the order of set is not stable
    # among different Python versions.
    presentation.logs['build_targets'] = str(
        {k: sorted(v) for k, v in dict(build_targets).items()})

    sorted_builds_len = len(sorted_builds)
    previously_updated_builds_len = (
        sum([len(v) for v in finished_builds.values()]) -
        sum([len(v) for v in build_targets.values()]))
    prebuilt_entries_len = (
        len(public_prebuilt_entries) + len(private_prebuilt_entries))
    running_builds_len = len(running_builds)
    presentation.step_text = (
        f'Total {sorted_builds_len} builds:\n'
        f'- {previously_updated_builds_len} previously-updated builds\n'
        f'- {prebuilt_entries_len} succeeded builds with uploaded prebuilts\n'
        f'- {running_builds_len} running builds\n')

  return public_prebuilt_entries, private_prebuilt_entries, running_builds


def set_binhosts(api: RecipeApi, step_name: str, is_staging: bool,
                 public_prebuilt_entries: List[dict],
                 private_prebuilt_entries: List[dict],
                 finished_builds: Dict[str, Set[str]]) -> None:
  """Utility function to set the binhosts repeatedly.

  Args:
    api: See RunSteps documentation.
    step_name: Name of the step of this process to be shown in the Luci UI.
    public_prebuilt_entries: Public prebuilts to be set the binhosts of.
    private_prebuilt_entries: Prebuilts prebuilts to be set the binhosts of.
    finished_builds: Dict to store the build_target and profiles of the
        finished builds. See the comment in `update_prebuilts()` for detail.
  """
  with api.step.nest(step_name) as presentation_set_binhost:
    # Count the number of builders that have generated prebuilts, and use it
    # as the maximum number of binhosts.
    # TODO(b/291943391): Support separated BINHOST.conf files for each
    # profiles and remove this hack.
    cumulative_binhost_counter = ({
        k: len(v) for k, v in finished_builds.items()
    })
    presentation_set_binhost.logs['cumulative_binhost_counter'] = (
        str(cumulative_binhost_counter))

    # Processes public builders
    with api.step.nest('Public binhosts') as presentation:
      public_prebuilt_entries_len = len(public_prebuilt_entries)
      presentation.step_summary_text = (
          f'Set {public_prebuilt_entries_len} binhosts.')
      if public_prebuilt_entries_len:
        with api.cros_build_api.parallel_operations():
          api.cros_prebuilts.set_binhosts(
              binhosts=list(
                  map(lambda e: (e['build_target'], e['prebuilts_uri']),
                      public_prebuilt_entries)),
              private=False,
              key=binhost_pb.CQ_BINHOST,
              overriding_max_uris=(cumulative_binhost_counter
                                   if is_staging else None),
          )

    # Processes private builders.
    with api.step.nest('Private binhosts') as presentation:
      private_prebuilt_entries_len = len(private_prebuilt_entries)
      presentation.step_summary_text = (
          f'Set {private_prebuilt_entries_len} binhosts.')
      if private_prebuilt_entries_len:
        with api.cros_build_api.parallel_operations():
          api.cros_prebuilts.set_binhosts(
              binhosts=list(
                  map(lambda e: (e['build_target'], e['prebuilts_uri']),
                      private_prebuilt_entries)),
              private=True,
              key=binhost_pb.CQ_BINHOST,
              overriding_max_uris=(cumulative_binhost_counter
                                   if is_staging else None),
          )


def update_prebuilts(api, builds, gerrit_change, is_staging,
                     entire_timeout_sec):
  """Utility function to try updating the prebuilts.

  If there are pending operations, after waiting for their completion, the
  logic tries updating them again.

  Args:
    api: See RunSteps documentation.
    builds: Name of the step of this process to be shown in the Luci UI.
    gerrit_change: The gerrit changes to get the corresponding prebuilts to.
    is_staging: True if wants the results from the staging environment.
    entire_timeout_sec: Duration to time out the entire operation.
  """

  # Parameters for the exponential-backoff retries.
  INITIAL_TIMEOUT_SEC = 2 * 60
  MAXIMUM_TIMEOUT_SEC = 30 * 60
  MULTIPLIER_ON_NOT_FOUND = 2
  start_time = time.time()

  # A dict storing the finished builds, like:
  #   finished_builds = {
  #     'build_target1': set('builder_name1'),
  #     'build_target2': set('builder_name2A', 'builder_name2B', ...),
  #     ...
  #   }
  finished_builds = defaultdict(set)
  timeout = INITIAL_TIMEOUT_SEC
  count = 1
  while True:
    name_suffix = '' if count == 1 else f' ({count})'
    public_prebuilt_entries, private_prebuilt_entries, running_builds = \
        search_prebuilts(api, 'search the prebuilts' + name_suffix, builds,
                         gerrit_change, finished_builds, is_staging)
    # Set None for 2nd runs and later to retrieve the latest builds.
    builds = None

    if len(public_prebuilt_entries) > 0 or len(private_prebuilt_entries) > 0:
      # If any builder finishes, set their binhosts.
      set_binhosts(api, 'set BINHOSTs' + name_suffix, is_staging,
                   public_prebuilt_entries, private_prebuilt_entries,
                   finished_builds)
    else:
      # Waiting with an exponential backoff algorithm if no builder finishes.
      timeout = min(timeout * MULTIPLIER_ON_NOT_FOUND, MAXIMUM_TIMEOUT_SEC)

    running_builds_len = len(running_builds)
    if running_builds_len == 0:
      # There are no running builders to wait for. Finishes the task.
      break

    finished_builds_len = sum([len(v) for v in finished_builds.values()])
    all_builds_len = finished_builds_len + running_builds_len

    # Adding one sec is a hack for test.
    if (time.time() - start_time + 1) >= entire_timeout_sec:
      return '\n'.join([
          f'Updated {finished_builds_len} of {all_builds_len} ' +
          f'builders after {count} trials.',
          f'Interrupted: maximum running time ({entire_timeout_sec} sec) ' +
          'exceeded.',
      ])

    with api.step.nest(f'waiting {timeout} sec for next retry') as presentation:
      presentation.step_summary_text = \
          f'{running_builds_len} of {all_builds_len} builds still running.'
      api.m.time.sleep(timeout)

    count += 1

  finished_builds_len = sum([len(v) for v in finished_builds.values()])
  return (f'Updated all of {finished_builds_len} builders after ' +
          f'{count} trials.')


def RunSteps(api: RecipeApi, properties: UploadPrebuiltsFromCqProperties):
  timeout_sec = properties.timeout_sec or TIMEOUT_SEC

  summary = DoRunSteps(api, timeout_sec) or ''
  return RawResult(status=common_pb2.SUCCESS, summary_markdown=summary)


def DoRunSteps(api: RecipeApi, entire_timeout_sec: int) -> Optional[str]:
  is_staging = api.build_menu.is_staging

  # Load of builder configurations first to make the result clear.
  api.cros_infra_config.force_reload()

  with api.step.nest('search the last merged uprev CL') as pres_search_cls:
    change = get_last_merged_change(api)

    if change is None:
      pres_search_cls.step_summary_text = 'Found no CL. Finishing.'
      return 'Found no CL'

    gitiles_triggers = [
        t for t in api.scheduler.triggers if t.HasField('gitiles')
    ]
    current_revision = change.get('current_revision')

    pres_search_cls.logs['change'] = str(change)
    pres_search_cls.logs['gitiles_triggers'] = str(gitiles_triggers)

    # Interrupt the job, if the job is triggered by gitiles but the trigger is
    # not the uprev commit.
    if len(gitiles_triggers) > 0:
      triggered_from_correct_cl = any(
          t.gitiles.revision == current_revision for t in gitiles_triggers)
      if not triggered_from_correct_cl:
        pres_search_cls.step_summary_text = \
            "The trigger of this job isn't the latest uprev commit. Finishing."
        return "The trigger isn't the latest uprev commit."

    change_num = change['_number']
    pres_search_cls.step_summary_text = \
        f'Found http://crrev.com/c/{change_num}'

  with api.step.nest('search the patchset') as presentation:
    if not 'revisions' in change or len(change['revisions']) == 0:
      raise StepFailure('no revisions in the change')

    landed_patchset = change['revisions'][current_revision]['_number']

    builds = []

    # Traverse the patchsets in reverse order to get the latest one with
    # successful CQ.
    for patchset in reversed(range(1, landed_patchset)):
      with api.step.nest(f'patchset #{patchset}'):
        gerrit_change = GerritChange(
            host=GERRIT_HOST,
            project=PUBLIC_OVERLAY_PROJECT,
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

  with api.cros_source.checkout_overlays_context(
  ), api.workspace_util.sync_to_commit(staging=is_staging,
                                       projects=BINHOST_PROJECTS):
    return update_prebuilts(api, builds, gerrit_change, is_staging,
                            entire_timeout_sec)


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
          PUBLIC_OVERLAY_PROJECT,
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

  GITILES_TRIGGER_UPREV_COMMIT = triggers_pb2.Trigger(
      id=str(CHANGE['_number']),
      gitiles=triggers_pb2.GitilesTrigger(
          repo=PUBLIC_OVERLAY_PROJECT,
          revision=CHANGE['current_revision'],
      ),
  )

  GITILES_TRIGGER_NON_UPREV_COMMIT = triggers_pb2.Trigger(
      id='33333',
      gitiles=triggers_pb2.GitilesTrigger(
          repo=PUBLIC_OVERLAY_PROJECT,
          revision='3333333333333333333333333333333333333333',
      ),
  )

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
      # Completed successfully on atlas (staging).
      build_pb2.Build(
          id=8922054662172514002,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'atlas'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338802),
          builder={
              'builder': 'staging-atlas-cq',
              'bucket': 'staging'
          },
      ),
      # Completed successfully on atlas (prod).
      build_pb2.Build(
          id=8922054662172514003,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'atlas'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338803),
          builder={
              'builder': 'atlas-cq',
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
      # Completed successfully on amd64-generic-asan (non-default profile).
      build_pb2.Build(
          id=8922054662175514000,
          status=common_pb2.SUCCESS,
          input=api.build_plan.input_proto(None, 'amd64-generic'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=False),
          create_time=timestamp_pb2.Timestamp(seconds=1598338800),
          builder={
              'builder': 'amd64-generic-asan',
              'bucket': 'informational',
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
      # Completed successfully on atlas (prod).
      build_pb2.Build(
          id=8922054662172514003,
          status=common_pb2.STARTED,
          input=api.build_plan.input_proto(None, 'atlas'),
          output=gen_output_props(prebuilts_uri='xxx', prebuilts_private=True),
          create_time=timestamp_pb2.Timestamp(seconds=1598338803),
          builder={
              'builder': 'atlas-cq',
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update brya'),
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update brya'),
      # Should update 3 amd64-generic and 2 atlas.
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic (2)'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic (3)'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas (2)'),
      # Should update 5 builders in total.
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 5 builders after 1 trials.'),
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update brya'),
      api.post_check(post_process.MustRun, 'waiting 120 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs (2).Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).Private binhosts.update brya'),
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs.Private binhosts.update brya'),
      api.post_check(post_process.MustRun, 'waiting 120 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).Public binhosts.update amd64-generic'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (2).Private binhosts.update brya'),
      api.post_check(post_process.MustRun, 'waiting 240 sec for next retry'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (3).Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs (3).Private binhosts.update atlas'),
      api.post_check(post_process.DoesNotRun,
                     'set BINHOSTs (3).Private binhosts.update brya'),
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
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
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(
          post_process.SummaryMarkdown,
          'Updated 1 of 2 builders after 1 trials.\nInterrupted: maximum running time (1 sec) exceeded.'
      ),
  )

  yield api.build_menu.test(
      'triggered-by-correct-uprev-commit',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.buildbucket.simulated_search_results(
          BUILDS,
          step_name='search the patchset.patchset #2.buildbucket.search',
      ),
      api.scheduler(triggers=[GITILES_TRIGGER_UPREV_COMMIT]),
      api.post_check(post_process.MustRun, 'search the prebuilts'),
      api.post_check(post_process.MustRun, 'set BINHOSTs'),
      # Should update 3 amd64-generic and 2 atlas.
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic (2)'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Public binhosts.update amd64-generic (3)'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas'),
      api.post_check(post_process.MustRun,
                     'set BINHOSTs.Private binhosts.update atlas (2)'),
      # Should update 5 builders in total.
      api.post_check(post_process.SummaryMarkdown,
                     'Updated all of 5 builders after 1 trials.'),
      bucket='staging',
  )

  yield api.build_menu.test(
      'triggered-by-non-uprev-commit',
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 1),
      api.gerrit.set_query_changes_response('search the last merged uprev CL',
                                            [CHANGE], GERRIT_HOST_URL, 2),
      api.scheduler(triggers=[GITILES_TRIGGER_NON_UPREV_COMMIT]),
      api.post_check(post_process.DoesNotRun, 'search the prebuilts'),
      api.post_check(post_process.SummaryMarkdown,
                     "The trigger isn't the latest uprev commit."),
      bucket='staging',
  )
