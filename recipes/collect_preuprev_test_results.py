# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that retrieves the result of tests executed before Chrome Uprev to
CrOS and warns on failure.
"""

import re
from typing import Any, List, Optional
from collections import OrderedDict

from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from PB.recipes.chromeos.collect_preuprev_test_results import (
    CollectPreuprevTestResults)
from RECIPE_MODULES.chromeos.gerrit.api import JSONObject as GerritJSONObject

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'cros_source',
    'gerrit',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_tags',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CollectPreuprevTestResults

GERRIT_HOST = 'chromium-review.googlesource.com'
CHROMIUM_PROJECT = 'chromium/src'

PUPR_GENERATOR_BUILDER_NAME = 'lacros-ash-atomic-pupr-generator'

# List of pre-uprev test builders:
PRE_UPREV_TEST_BUILDERS = [
    'chromeos-brya-chrome-skylab',
    'chromeos-jacuzzi-chrome-skylab',
    'chromeos-volteer-chrome-skylab',
    'chromeos-betty-pi-arc-chrome',
    'chromeos-betty-arc-r-chrome',
    'linux-chromeos-chrome',
]


def GetPreUprevTestBuilders(api: RecipeApi, release_task_id: int):
  results = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(child_of=release_task_id), fields=[
          'id', 'output', 'steps', 'summary_markdown', 'cancellation_markdown'
      ])

  r = []
  for result in results:
    if result.builder.builder in PRE_UPREV_TEST_BUILDERS:
      r.append(result)
  return r


def GetPuprGeneratorBuilder(api: RecipeApi, pupr_cordinator_task_id: int):
  builds = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(child_of=pupr_cordinator_task_id),
      fields=[
          'id', 'output', 'steps', 'summary_markdown', 'cancellation_markdown'
      ])

  for build in builds:
    if build.builder.builder == PUPR_GENERATOR_BUILDER_NAME:
      return build

  return None


def GetUprevClNumber(pupr_generator_task: build_pb2.Build) -> Optional[int]:
  PREFIX = 'created https://crrev.com/c/'
  if pupr_generator_task.summary_markdown.startswith(PREFIX):
    PREFIX_LEN = len(PREFIX)
    return int(pupr_generator_task.summary_markdown[PREFIX_LEN:])

  PATTERN = r'chromium:(\d+)'
  pattern_result = re.search(PATTERN, pupr_generator_task.summary_markdown)
  if pattern_result:
    return int(pattern_result.group(1))

  return None


def RunSteps(api: RecipeApi, properties: CollectPreuprevTestResults):
  api.cros_source.configure_builder(default_main=True)

  current_build_id = (
      properties.current_build_id_overridden_for_testing or
      api.buildbucket.build.id)
  uprev_cl_number_overridden_for_testing = (
      properties.uprev_cl_number_overridden_for_testing
      if properties.uprev_cl_number_overridden_for_testing != 0 else None)

  with api.cros_source.checkout_overlays_context():
    return DoRunSteps(api, current_build_id,
                      uprev_cl_number_overridden_for_testing)


def DoRunSteps(api: RecipeApi, current_build_id: int,
               uprev_cl_number_overridden_for_testing: Optional[int]):
  with api.step.nest('Find pupr-coordinator builder') as presentation:
    current_task = api.buildbucket.get(current_build_id,
                                       fields=['ancestor_ids'])
    if len(current_task.ancestor_ids) < 2:
      return RawResult(
          status=common_pb2.FAILURE,
          summary_markdown='Failed to retrieve ancestor build IDs.')

    pupr_cordinator_task_id = current_task.ancestor_ids[-1]
    release_task_id = current_task.ancestor_ids[-2]

    summary_text = (
        f'- pupr-coordinator: [bbid/{pupr_cordinator_task_id}]' +
        f'(https://ci.chromium.org/ui/b/{pupr_cordinator_task_id})\n' +
        f'- chrome-release: [bbid/{release_task_id}]' +
        f'(https://ci.chromium.org/ui/b/{release_task_id})\n')

    presentation.step_summary_text = summary_text

  with api.step.nest('Find pre-uprev tests') as presentation:
    pre_uprev_builder_ids = []
    pre_uprev_builders = GetPreUprevTestBuilders(api, release_task_id)
    for builder in pre_uprev_builders:
      pre_uprev_builder_ids.append(int(builder.id))
    presentation.step_summary_text = ''.join(
        map(
            lambda b: f'- {b.builder.builder}: ' +
            f'[bbid/{b.id}](https://ci.chromium.org/ui/b/{b.id})\n',
            pre_uprev_builders))

  with api.step.nest('Wait for completion of pre-uprev tests') as presentation:
    PRE_UPREV_TEST_TIMEOUT = 6 * 60 * 60  # 6 hour
    api.buildbucket.collect_builds(pre_uprev_builder_ids,
                                   timeout=PRE_UPREV_TEST_TIMEOUT)

  with api.step.nest(
      'Wait for completion of pupr-generator builder') as presentation:
    PUPR_GENERATOR_INTERVAL = 5 * 60  # 5 min
    PUPR_GENERATOR_TIMEOUT = 30 * 60  # 30 min

    with api.time.timeout(seconds=PUPR_GENERATOR_TIMEOUT):
      while True:
        pupr_generator_task = GetPuprGeneratorBuilder(api,
                                                      pupr_cordinator_task_id)

        # Exit the loop if the pupr generator has finished.
        if pupr_generator_task is not None and (pupr_generator_task.status
                                                & common_pb2.ENDED_MASK) != 0:
          presentation.step_summary_text = (
              f'pupr-generator: [bbid/{pupr_generator_task.id}]' +
              f'(https://ci.chromium.org/ui/b/{pupr_generator_task.id})')
          break

        # The pupr generator has not started or is still running.
        # Will retry after the sleep.
        api.time.sleep(secs=PUPR_GENERATOR_INTERVAL, with_step=True)

    if pupr_generator_task.status != common_pb2.SUCCESS:
      return RawResult(status=common_pb2.FAILURE,
                       summary_markdown='Pupr generator has failed')

  with api.step.nest('Find the uprev CL') as presentation:
    uprev_cl_number = GetUprevClNumber(pupr_generator_task)
    if uprev_cl_number is not None:
      presentation.step_summary_text = (
          f'[chromium:{uprev_cl_number}](https://crrev.com/c/{uprev_cl_number})'
      )
    else:
      presentation.step_summary_text = (
          'Uprev CL is not found. Probably it is not generated?')
      return RawResult(status=common_pb2.FAILURE,
                       summary_markdown='Uprev CL is not found.')

  with api.step.nest('Prepare the result message') as presentation:
    successful_builds = []
    failed_builds = []
    for builder in pre_uprev_builders:
      if builder.status == common_pb2.SUCCESS:
        successful_builds.append(
            f' - {builder.builder.builder}: ' +
            f'[build page](https://ci.chromium.org/ui/b/{builder.id})\n')
      else:
        failed_builds.append(
            f' - {builder.builder.builder}: ' +
            f'[build page](https://ci.chromium.org/ui/b/{builder.id})\n')

    total_build_len = len(pre_uprev_builders)

    text = '[EXPERIMENTAL] Pre-uprev test result: '
    if not failed_builds:
      text += 'All builds succeeded\n\n'
    else:
      text += f'{len(failed_builds)} of {total_build_len} builds failed\n\n'

    if failed_builds:
      text += '---\n\n'
      text += 'Failed builds '
      text += f'({len(failed_builds)} of {total_build_len} builds):\n\n'
      text += ''.join(failed_builds)
    if successful_builds:
      text += '---\n\n'
      text += 'Successful builds '
      text += f'({len(successful_builds)} of {total_build_len} builds):\n\n'
      text += ''.join(successful_builds)

    text += '\n'
    if failed_builds:
      text += 'Please stop the uprev if the failure is critical. '
    text += 'Ask yoshiki@ on the gardener chat if you have a question.'

    presentation.logs['generated message'] = text

  with api.step.nest('Find the uprev CL on gerrit') as presentation:
    if uprev_cl_number_overridden_for_testing is not None:
      with api.step.nest('Overriding Uprev CL number as testing') as prep:
        prep.summary_text = (
            f'{uprev_cl_number} => {uprev_cl_number_overridden_for_testing}')
        uprev_cl_number = uprev_cl_number_overridden_for_testing

    uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                                change=uprev_cl_number, patchset=1)

    uprev_change_data = api.gerrit.fetch_patch_set_from_change(uprev_change)
    presentation.step_summary_text = (
        f'[chromium:{uprev_cl_number}](https://crrev.com/c/{uprev_cl_number})' +
        f' {uprev_change_data.status}')

    if uprev_change_data.status != 'NEW':
      return RawResult(status=common_pb2.FAILURE,
                       summary_markdown='Uprev CL is not clean state')

  with api.step.nest('Add a comment to the uprev CL') as presentation:
    presentation.step_summary_text = f'https://crrev.com/c/{uprev_cl_number}'

    uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                                change=uprev_cl_number)
    api.gerrit.add_change_comment_remote(uprev_change, text)

    overall_summary = (
        'Add a message to ' +
        f'[chromium:{uprev_cl_number}](https://crrev.com/c/{uprev_cl_number})')

  return RawResult(status=common_pb2.SUCCESS, summary_markdown=overall_summary)


def GenTests(api: RecipeTestApi):
  UPREV_GERRIT_CHANGE_VALUES = {
      'change_id': '1',
      'status': 'NEW',
  }
  UPREV_GERRIT_CHANGE_VALUES_MERGED = {
      'change_id': '1',
      'status': 'MERGED',
  }

  BRANCHING_BUILDER_ID = 101
  RELEASING_BUILDER_ID = 102
  PUPR_GENERATOR_BUILD_ID = 300
  CURRENT_BUILD_ID = 301

  PUPR_GENERATOR_BUILD_OLD = build_pb2.Build(
      id=PUPR_GENERATOR_BUILD_ID, status=common_pb2.SUCCESS,
      builder=builder_common_pb2.BuilderID(builder=PUPR_GENERATOR_BUILDER_NAME),
      summary_markdown='created https://crrev.com/c/123456')
  PUPR_GENERATOR_BUILD = build_pb2.Build(
      id=PUPR_GENERATOR_BUILD_ID, status=common_pb2.SUCCESS,
      builder=builder_common_pb2.BuilderID(builder=PUPR_GENERATOR_BUILDER_NAME),
      summary_markdown='created [chromium:123456](https://crrev.com/c/123456)')
  PUPR_GENERATOR_BUILD_RUNNING = build_pb2.Build(
      id=PUPR_GENERATOR_BUILD_ID, status=common_pb2.STARTED,
      builder=builder_common_pb2.BuilderID(builder=PUPR_GENERATOR_BUILDER_NAME))
  PUPR_GENERATOR_BUILD_FAILED = build_pb2.Build(
      id=PUPR_GENERATOR_BUILD_ID, status=common_pb2.FAILURE,
      builder=builder_common_pb2.BuilderID(builder=PUPR_GENERATOR_BUILDER_NAME),
      summary_markdown='failed')
  PUPR_GENERATOR_BUILD_WITHOUT_GENERATION = build_pb2.Build(
      id=PUPR_GENERATOR_BUILD_ID, status=common_pb2.SUCCESS,
      builder=builder_common_pb2.BuilderID(builder=PUPR_GENERATOR_BUILDER_NAME),
      summary_markdown='[retry-only] success')

  PRE_UPREV_TEST_BUILDER_1 = build_pb2.Build(
      id=201, status=common_pb2.SUCCESS, builder=builder_common_pb2.BuilderID(
          builder='chromeos-jacuzzi-chrome-skylab'))
  PRE_UPREV_TEST_BUILDER_2 = build_pb2.Build(
      id=202, status=common_pb2.SUCCESS, builder=builder_common_pb2.BuilderID(
          builder='chromeos-brya-chrome-skylab'))
  PRE_UPREV_TEST_BUILDER_FAILED = build_pb2.Build(
      id=203, status=common_pb2.FAILURE, builder=builder_common_pb2.BuilderID(
          builder='chromeos-jacuzzi-chrome-skylab'))

  CURRENT_BUILD = build_pb2.Build(
      id=CURRENT_BUILD_ID, ancestor_ids=[
          BRANCHING_BUILDER_ID, RELEASING_BUILDER_ID, PUPR_GENERATOR_BUILD_ID
      ])

  # helper method to generate a test.
  def test(name: str, *args: Any, current_build: build_pb2.Build,
           pupr_generater_build_resps: Optional[List[build_pb2.Build]] = None,
           uprev_test_builds: Optional[List[build_pb2.Build]] = None,
           uprev_gerrit_change: Optional[GerritJSONObject] = None,
           **kwargs: Any):
    build = api.buildbucket.build(current_build)
    build += api.buildbucket.simulated_get(
        current_build,
        step_name='Find pupr-coordinator builder.buildbucket.get')

    PUPR_GENERATOR_STEP_NAME = 'Wait for completion of pupr-generator builder'
    if pupr_generater_build_resps:
      for i, pupr_generater_build in enumerate(pupr_generater_build_resps):
        step_name = PUPR_GENERATOR_STEP_NAME + '.buildbucket.search'
        suffix = '' if i == 0 else f' ({i + 1})'
        pupr_generater_builds = ([pupr_generater_build]
                                 if pupr_generater_build else [])

        build += api.buildbucket.simulated_search_results(
            pupr_generater_builds,
            step_name=step_name + suffix,
        )
      # Confirms no query more than `pupr_generater_build_resps`.
      build += api.post_check(
          post_process.DoesNotRun,
          PUPR_GENERATOR_STEP_NAME + f' {len(pupr_generater_build_resps) + 1}')
    else:
      build += api.post_check(post_process.DoesNotRun, PUPR_GENERATOR_STEP_NAME)

    PREUPREV_STEP_NAME = 'Find pre-uprev tests.buildbucket'
    if uprev_test_builds:
      build += api.buildbucket.simulated_search_results(
          uprev_test_builds,
          step_name=PREUPREV_STEP_NAME + '.search',
      )
    else:
      build += api.post_check(post_process.DoesNotRun, PREUPREV_STEP_NAME)

    UPREV_GERRIT_CHANGE_STEP_NAME = 'Find the uprev CL on gerrit'
    if uprev_gerrit_change:
      change_id = int(uprev_gerrit_change['change_id'])
      data = OrderedDict({change_id: uprev_gerrit_change})
      build += api.gerrit.set_gerrit_fetch_changes_response(
          UPREV_GERRIT_CHANGE_STEP_NAME, [
              GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                           change=change_id, patchset=1)
          ], data)
    else:
      build += api.post_process(post_process.DoesNotRun,
                                UPREV_GERRIT_CHANGE_STEP_NAME)

    return api.test(name, build, *args, **kwargs)

  yield test(
      'tests-succeeded',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          PRE_UPREV_TEST_BUILDER_1,
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  yield test(
      'tests-succeeded-old',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD_OLD],
      uprev_test_builds=[
          PRE_UPREV_TEST_BUILDER_1,
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  yield test(
      'tests-failed',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          # Returns a failed pre-uprev test builder.
          PRE_UPREV_TEST_BUILDER_FAILED
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  # Simulates that the uprev CL is already merged.
  yield test(
      'uprev-cl-already-merged',
      api.post_check(post_process.DoesNotRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      status='FAILURE',
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          PRE_UPREV_TEST_BUILDER_1,
          PRE_UPREV_TEST_BUILDER_2,
      ],
      # Returns the merged chrome uprev CL.
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES_MERGED,
  )

  # Simulates that the recipe can wait and retry when the pupr generator is not
  # finished yet.
  yield test(
      'wait-for-pupr-generator',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[
          # First query: No pupr-generator in the result.
          None,
          # Second query: One running pupr-generator in the result.
          PUPR_GENERATOR_BUILD_RUNNING,
          # Third query: One finished pupr-generator in the result.
          PUPR_GENERATOR_BUILD
      ],
      uprev_test_builds=[
          PRE_UPREV_TEST_BUILDER_1,
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  # Simulates when the pupr generator has failed.
  yield test(
      'pupr-generator-failed',
      status='FAILURE',
      current_build=CURRENT_BUILD,
      # Returns a failed pupr-generator build.
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD_FAILED],
  )

  # Simulates when the pupr generator has not generated the uprev CL.
  yield test(
      'pupr-generator-not-generated-cl',
      status='FAILURE',
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD_WITHOUT_GENERATION],
  )

  # Checks if `uprev_cl_number_overridden_for_testing` works.
  yield test(
      'overriding-gerrit-uprev-cl-number',
      api.properties(uprev_cl_number_overridden_for_testing=98765),
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 98765'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          PRE_UPREV_TEST_BUILDER_1,
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  # Fails if this build has less than 2 ancestor builds
  yield test(
      'invalid-current-task',
      status='FAILURE',
      # Invalid current build with less ancestor id
      current_build=build_pb2.Build(id=CURRENT_BUILD_ID, ancestor_ids=[99999]),
  )
