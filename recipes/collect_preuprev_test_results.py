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
from PB.go.chromium.org.luci.lucictx import (
    sections as sections_pb2,)

from PB.recipes.chromeos.collect_preuprev_test_results import (
    CollectPreuprevTestResults)
from RECIPE_MODULES.chromeos.gerrit.api import JSONObject as GerritJSONObject
from RECIPE_MODULES.chromeos.gerrit.api import Label, PatchSet

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

from google.protobuf import json_format
from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/context',
    'cros_source',
    'cros_tags',
    'gerrit',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
]


PROPERTIES = CollectPreuprevTestResults

GERRIT_HOST = 'chromium-review.googlesource.com'
CHROMIUM_PROJECT = 'chromium/src'

PUPR_GENERATOR_BUILDER_NAME = 'lacros-ash-atomic-pupr-generator'

# List of pre-uprev test builders:
PRE_UPREV_TEST_BUILDERS = [
    'chromeos-brya-chrome-preuprev',
    'chromeos-jacuzzi-chrome-preuprev',
    'chromeos-volteer-chrome-preuprev',
    'chromeos-betty-chrome-preuprev',
    'chromeos-betty-pi-arc-chrome-preuprev',
    'linux-chromeos-chrome-preuprev',

    # Old builders. Remove them after migrating to new builders (*-preuprev).
    'chromeos-brya-chrome-skylab',
    'chromeos-jacuzzi-chrome-skylab',
    'chromeos-volteer-chrome-skylab',
    'chromeos-betty-pi-arc-chrome',
    'chromeos-betty-arc-r-chrome',
    'linux-chromeos-chrome',
]

BUILD_FIELDS_TO_RETRIEVE = [
    'builder',
    'cancellation_markdown',
    'id',
    'input',
    'output',
    'status',
    'steps',
    'summary_markdown',
    'infra.resultdb',
]

RETRY_PREUPREV_MAX_COUNT = 1


def GetPreUprevTestBuilders(api: RecipeApi, release_task_id: int):
  results = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(child_of=release_task_id),
      fields=BUILD_FIELDS_TO_RETRIEVE)

  r = []
  for result in results:
    if result.builder.builder in PRE_UPREV_TEST_BUILDERS:
      r.append(result)
  return r


def GetPuprGeneratorBuilder(api: RecipeApi, pupr_cordinator_task_id: int):
  builds = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(child_of=pupr_cordinator_task_id),
      fields=BUILD_FIELDS_TO_RETRIEVE)

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


def ToBuilderIds(builders: List[build_pb2.Build]) -> List[int]:
  return list(map(lambda b: int(b.id), builders))


def QuoteMd(s: Optional[str]) -> str:
  if not s:
    return ''
  result = ''
  for l in s.splitlines():
    result += '> '
    result += l
    result += '\n'
  return result


def ToBuildersLinkMd(builders: List[build_pb2.Build],
                     include_details=False) -> str:
  text = ''
  for builder in builders:
    status = common_pb2.Status.Name(builder.status)
    text += (f'- {builder.builder.builder}: ' +
             f'[{status}](https://ci.chromium.org/ui/b/{builder.id})\n')
    if include_details:
      text += QuoteMd(builder.summary_markdown)
  return text


def FilterBuildsStatus(builders: List[build_pb2.Build],
                       status: common_pb2.Status):
  true_builders, false_builders = [], []
  for builder in builders:
    if builder.status == status:
      true_builders.append(builder)
    else:
      false_builders.append(builder)
  return true_builders, false_builders


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
    # Wait for up to 10 minutes until pre-uprev builder is scheduled.
    PRE_UPREV_SCHEDULE_DEALAY = 10 * 60  # 10 min
    api.time.sleep(secs=PRE_UPREV_SCHEDULE_DEALAY, with_step=True)

    pre_uprev_builders = GetPreUprevTestBuilders(api, release_task_id)

    presentation.step_summary_text = ''.join(
        map(
            lambda b: f'- {b.builder.builder}: ' +
            f'[bbid/{b.id}](https://ci.chromium.org/ui/b/{b.id})\n',
            pre_uprev_builders))

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

  with api.step.nest('Find the uprev CL on gerrit') as presentation:
    if uprev_cl_number_overridden_for_testing is not None:
      with api.step.nest('Overriding Uprev CL number as testing') as prep:
        prep.summary_text = (
            f'{uprev_cl_number} => {uprev_cl_number_overridden_for_testing}')
        uprev_cl_number = uprev_cl_number_overridden_for_testing

    uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                                change=uprev_cl_number, patchset=1)

    uprev_change_data = api.gerrit.fetch_patch_set_from_change(
        uprev_change, include_detailed_labels=True, include_commit_info=True)
    presentation.step_summary_text = (
        f'[{uprev_change_data.display_id}]({uprev_change_data.display_url})' +
        f' {uprev_change_data.status}')

  with api.step.nest('Post progress message') as presentation:
    text = 'Pre-Uprev Test RUNNING\n\n'
    text += '\n'

    text += ToBuildersLinkMd(pre_uprev_builders)

    text += '\n\n'
    text += ('Pre-uprev test verifies the soundness of upreved revision of '
             'chrome by running a small subset of tast tests with the upreved '
             'chrome + LKGM CrOS. The test is independent from CQ testing.\n\n')
    text += 'Please make sure pre-uprev test succeeds before submitting this CL!\n'
    presentation.logs['generated message'] = text
    uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                                change=uprev_change_data.change_id)
    api.gerrit.add_change_comment_remote(uprev_change, text)

  # Terminate early without waiting for preuprev results.
  if uprev_change_data.status != 'NEW':
    return RawResult(
        status=common_pb2.FAILURE, summary_markdown=(
            f'Uprev CL [{uprev_change_data.display_id}]({uprev_change_data.display_url})'
            ' is not clean state'))

  pre_uprev_builders = CollectResult(api, pre_uprev_builders, uprev_change_data)
  overall_summary = (
      f'CL: [{uprev_change_data.display_id}]({uprev_change_data.display_url})\n\n'
  )
  overall_summary += ToBuildersLinkMd(pre_uprev_builders, include_details=True)
  _, failed_builds = FilterBuildsStatus(pre_uprev_builders, common_pb2.SUCCESS)
  with api.step.nest('including pre-uprev builder results') as step:
    invocations = [
        i.infra.resultdb.invocation
        for i in pre_uprev_builders
        if i.infra.resultdb.invocation
    ]
    step.step_summary_text = '\n'.join(invocations)
    for inv in invocations:
      assert inv.startswith('invocations/')
    api.resultdb.include_invocations(
        [inv[len('invocations/'):] for inv in invocations],
        'include invocations from pre-uprev builders')
  return RawResult(
      status=common_pb2.FAILURE if failed_builds else common_pb2.SUCCESS,
      summary_markdown=overall_summary)


def DoRetry(api: RecipeApi, builder_to_retry: build_pb2.Build):
  with api.step.nest(
      f'retrying {builder_to_retry.builder.builder}') as presentation:
    request = api.buildbucket.schedule_request(
        project=builder_to_retry.builder.project,
        builder=builder_to_retry.builder.builder,
        bucket=builder_to_retry.builder.bucket,
        properties={
            'chrome_version':
                builder_to_retry.input.properties['chrome_version'],
            'triggers':
                builder_to_retry.input.properties['triggers'],
        },
        gitiles_commit=builder_to_retry.input.gitiles_commit,
        fields=BUILD_FIELDS_TO_RETRIEVE,
    )
    try:
      return api.buildbucket.schedule([request])[0]
    except api.step.InfraFailure:
      presentation.status = api.step.EXCEPTION
      return None


def CollectResult(api: RecipeApi, pre_uprev_builders: List[build_pb2.Build],
                  uprev_change_data: PatchSet):
  pre_uprev_builders = CollectSingleResult(api, pre_uprev_builders,
                                           uprev_change_data)

  for _ in range(0, RETRY_PREUPREV_MAX_COUNT):
    _, failed_builds = FilterBuildsStatus(pre_uprev_builders,
                                          common_pb2.SUCCESS)

    if not failed_builds:
      break

    new_pre_uprev_builders = []
    retried_builders = []
    with api.step.nest('retry failed builds'):
      for builder in pre_uprev_builders:
        if builder.status == common_pb2.SUCCESS:
          new_pre_uprev_builders.append(builder)
          continue
        new_builder = DoRetry(api, builder)
        if new_builder:
          new_pre_uprev_builders.append(new_builder)
          retried_builders.append(new_builder)
        else:
          new_pre_uprev_builders.append(builder)

    if retried_builders:
      text = 'Pre-Uprev Retrying Following Builders:\n\n'
      text += ToBuildersLinkMd(retried_builders)
      text += '\n\nPlease wait for retried builder to succeed before submission.'
      uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                                  change=uprev_change_data.change_id)
      api.gerrit.add_change_comment_remote(uprev_change, text)

      pre_uprev_builders = CollectSingleResult(api, new_pre_uprev_builders,
                                               uprev_change_data)

  return pre_uprev_builders


def CollectSingleResult(api: RecipeApi,
                        pre_uprev_builders: List[build_pb2.Build],
                        uprev_change_data: PatchSet):
  uprev_change = GerritChange(host=GERRIT_HOST, project=CHROMIUM_PROJECT,
                              change=uprev_change_data.change_id)

  with api.step.nest('Wait for completion of pre-uprev tests') as presentation:
    PRE_UPREV_TEST_TIMEOUT = 6 * 60 * 60  # 6 hour
    pre_uprev_builders = api.buildbucket.collect_builds(
        ToBuilderIds(pre_uprev_builders), fields=BUILD_FIELDS_TO_RETRIEVE,
        timeout=PRE_UPREV_TEST_TIMEOUT).values()

  with api.step.nest('Process pre-uprev results') as presentation:
    successful_builds, failed_builds = FilterBuildsStatus(
        pre_uprev_builders, common_pb2.SUCCESS)

    for builder in pre_uprev_builders:
      # Create steps that represent builder status of each builder as step
      # status.
      with api.step.nest(f'{builder.builder.builder}',
                         status='last') as task_step:
        if builder.status == common_pb2.FAILURE:
          task_step.status = api.step.FAILURE
        elif builder.status == common_pb2.SUCCESS:
          task_step.status = api.step.SUCCESS
        else:  # pragma: no cover
          task_step.status = api.step.EXCEPTION

    total_build_len = len(pre_uprev_builders)

  with api.step.nest('Add a comment to the uprev CL') as presentation:
    text = 'Pre-Uprev Test '
    if not failed_builds:
      text += 'PASSED: All builds succeeded\n\n'
    else:
      text += f'FAILED: {len(failed_builds)} of {total_build_len} builds failed\n\n'

    if failed_builds:
      text += '---\n\n'
      text += 'Failed builds '
      text += f'({len(failed_builds)} of {total_build_len} builds):\n\n'
      text += ToBuildersLinkMd(failed_builds, include_details=True)
    if successful_builds:
      text += '---\n\n'
      text += 'Successful builds '
      text += f'({len(successful_builds)} of {total_build_len} builds):\n\n'
      text += ToBuildersLinkMd(successful_builds)

    text += '\n'
    text += ('Pre-uprev test verifies the soundness of upreved revision of '
             'chrome by running a small subset of tast tests with the upreved '
             'chrome + LKGM CrOS. The test is independent from CQ testing.\n\n')
    if failed_builds:
      text += 'The pre-uprev test is NOT passed. '

      text += (
          'Please check the result of failed builders. If failures are real, '
          'please fix them and trigger (or wait) next uprev. If not, please '
          'set Verified+1 and add CR+2 manually.\n\n'
          'See http://go/cros-gardening-preuprev-test for detail.')
    else:
      text += 'The test is PASSED. No action required. Please wait for the result from CQ.'

    presentation.logs['generated message'] = text
    presentation.step_summary_text = uprev_change_data.display_url

    api.gerrit.add_change_comment_remote(uprev_change, text)

    if failed_builds:
      # Clear Bot-Commit set by pupr generator.
      # This would clear any overrides of Code-Review or Verified from
      # Bot-Commit.  Setting up Code-Review+1 alone won't stop automatic
      # submission as Bot-Commit will override Code-Review(except -2) and
      # Verified(except -1)
      # We cannot do Verified-1 since it will require gardeners to rebase the
      # CL to clear it. Rebasing the CL will change CL owner to the person and
      # the person may not have Code-Owners on modified files.
      api.gerrit.set_change_labels_remote(uprev_change, {
          Label.BOT_COMMIT: 0,
          Label.CODE_REVIEW: 1,
      })
    else:
      # Add BOT_COMMIT+1 to override Code-Review and Verified, and set
      # COMMIT_QUEUE+2 to trigger CQ submission.
      api.gerrit.set_change_labels_remote(uprev_change, {
          Label.BOT_COMMIT: 1,
          Label.COMMIT_QUEUE: 2,
      })

  return pre_uprev_builders

def GenTests(api: RecipeTestApi):
  UPREV_GERRIT_CHANGE_VALUES = {
      'change_id': '123456',
      'status': 'NEW',
      'labels': {
          'Commit-Queue': {
              'all': [{
                  'value': 2
              }]
          }
      }
  }
  UPREV_GERRIT_CHANGE_OVERRIDEN_VALUES = {
      'change_id': '98765',
      'status': 'NEW',
      'labels': {
          'Commit-Queue': {
              'all': [{
                  'value': 2
              }]
          }
      }
  }
  UPREV_GERRIT_CHANGE_VALUES_MERGED = {
      'change_id': '123456',
      'status': 'MERGED',
      'labels': {
          'Commit-Queue': {
              'all': [{
                  'value': 2
              }]
          }
      }
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
          builder='chromeos-jacuzzi-chrome-skylab'), infra=build_pb2.BuildInfra(
              resultdb=build_pb2.BuildInfra.ResultDB(
                  invocation='invocations/build-201-rdb'),
          ))
  PRE_UPREV_TEST_BUILDER_2 = build_pb2.Build(
      id=202,
      status=common_pb2.SUCCESS,
      builder=builder_common_pb2.BuilderID(
          # This one doesn't mock any invocation result to mimic any unexpected
          # case.
          builder='chromeos-brya-chrome-skylab'))
  PRE_UPREV_TEST_BUILDER_FAILED = build_pb2.Build(
      id=203, status=common_pb2.FAILURE, builder=builder_common_pb2.BuilderID(
          builder='chromeos-jacuzzi-chrome-skylab'),
      input=build_pb2.Build.Input(
          properties=json_format.Parse(
              api.json.dumps({
                  'chrome_version':
                      '129.0.6658.0',
                  'triggers': [{
                      'gitiles': {
                          'ref':
                              'refs/tags/129.0.6658.0',
                          'repo':
                              'https://chromium.googlesource.com/chromium/src',
                          'revision':
                              'b6b086b2111573c43c2f620cca8ccc7133a9dc2c',
                      },
                  },],
              }), struct_pb2.Struct()), gitiles_commit={
                  'host': 'chromium.googlesource.com',
                  'id': 'b6b086b2111573c43c2f620cca8ccc7133a9dc2c',
                  'project': 'chromium/src',
                  'ref': 'refs/tags/129.0.6658.0',
              }),
      summary_markdown='1 Test Suite(s) failed.\n\n**chrome_all_tast_tests RELEASE_LKGM** failed because of:\n\n- tast.audio.CrasDLCManager',
      infra=build_pb2.BuildInfra(
          resultdb=build_pb2.BuildInfra.ResultDB(
              invocation='invocations/build-203-rdb'),
      ))

  CURRENT_BUILD = build_pb2.Build(
      id=CURRENT_BUILD_ID, ancestor_ids=[
          BRANCHING_BUILDER_ID, RELEASING_BUILDER_ID, PUPR_GENERATOR_BUILD_ID
      ])

  # helper method to generate a test.
  def test(name: str, *args: Any, current_build: build_pb2.Build,
           pupr_generater_build_resps: Optional[List[build_pb2.Build]] = None,
           uprev_test_builds: Optional[List[build_pb2.Build]] = None,
           uprev_test_retry_builds: Optional[List[build_pb2.Build]] = None,
           uprev_test_retry_builds_creation_failed: Optional[List[str]] = None,
           uprev_gerrit_change: Optional[GerritJSONObject] = None,
           **kwargs: Any):
    build = api.buildbucket.build(current_build)
    build += api.context.luci_context(
        resultdb=sections_pb2.ResultDB(
            current_invocation=sections_pb2.ResultDBInvocation(
                name='invocations/inv-9999',
                update_token='token',
            ),
            hostname='rdbhost',
        ))
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

    PREUPREV_STEP_NAME = 'Find pre-uprev tests'
    PREUPREV_COLLECT_RESULT_NAME = 'Wait for completion of pre-uprev tests'
    if uprev_test_builds:
      build += api.buildbucket.simulated_search_results(
          uprev_test_builds,
          step_name=PREUPREV_STEP_NAME + '.buildbucket.search',
      )
      build += api.buildbucket.simulated_collect_output(
          uprev_test_builds,
          step_name=PREUPREV_COLLECT_RESULT_NAME + '.buildbucket.collect')
    else:
      build += api.post_check(post_process.DoesNotRun,
                              PREUPREV_STEP_NAME + '.buildbucket')
      build += api.post_check(post_process.DoesNotRun,
                              PREUPREV_COLLECT_RESULT_NAME + '.buildbucket')

    PREUPREV_COLLECT_RETRY_RESULT_NAME = 'Wait for completion of pre-uprev tests (2)'
    if uprev_test_retry_builds:
      for retry_build in uprev_test_retry_builds:
        build += api.buildbucket.simulated_schedule_output(
            builds_service_pb2.BatchResponse(
                responses=[{
                    'schedule_build': retry_build,
                }],
            ),
            step_name=f'retry failed builds.retrying {retry_build.builder.builder}.buildbucket.schedule'
        )

      collect_result = []
      for original_build in uprev_test_builds:
        has_retry_build = None
        for retry_build in uprev_test_retry_builds:
          if retry_build.builder.builder == original_build.builder.builder:
            has_retry_build = retry_build
            break
        if has_retry_build:
          collect_result.append(has_retry_build)
        else:
          collect_result.append(original_build)
      build += api.buildbucket.simulated_collect_output(
          collect_result,
          step_name=PREUPREV_COLLECT_RETRY_RESULT_NAME + '.buildbucket.collect')
    elif uprev_test_retry_builds_creation_failed:
      for builder in uprev_test_retry_builds_creation_failed:
        build += api.buildbucket.simulated_schedule_output(
            builds_service_pb2.BatchResponse(responses=[{
                'error': {
                    'code': 7,
                    'message': 'You do not have permission to schedule.'
                }
            }]),
            step_name=f'retry failed builds.retrying {builder}.buildbucket.schedule'
        )
      build += api.post_process(post_process.DoesNotRun,
                                PREUPREV_COLLECT_RETRY_RESULT_NAME)
    else:
      build += api.post_check(
          post_process.DoesNotRun,
          PREUPREV_COLLECT_RETRY_RESULT_NAME + '.buildbucket')
      build += api.post_check(post_process.DoesNotRun, 'retry failed builds')

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
      api.post_check(
          post_process.MustRun,
          'Add a comment to the uprev CL (2).add comment on CL 123456'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results.chromeos-jacuzzi-chrome-skylab'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results (2).chromeos-jacuzzi-chrome-skylab'),
      status='FAILURE',
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          # Returns a failed pre-uprev test builder.
          PRE_UPREV_TEST_BUILDER_FAILED
      ],
      uprev_test_retry_builds=[
          # Retry also failed
          PRE_UPREV_TEST_BUILDER_FAILED,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  yield test(
      'tests-failed-retry-creation-failed',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      api.post_check(
          post_process.DoesNotRun,
          'Add a comment to the uprev CL (2).add comment on CL 123456'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results.chromeos-jacuzzi-chrome-skylab'),
      api.post_process(
          post_process.DoesNotRun,
          'Process pre-uprev results (2).chromeos-jacuzzi-chrome-skylab'),
      api.post_process(
          post_process.StepException,
          'retry failed builds.retrying chromeos-jacuzzi-chrome-skylab'),
      status='FAILURE',
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          # Returns a failed pre-uprev test builder.
          PRE_UPREV_TEST_BUILDER_FAILED
      ],
      uprev_test_retry_builds_creation_failed=[
          # Retry build failed to schedule
          PRE_UPREV_TEST_BUILDER_FAILED.builder.builder,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  yield test(
      'retry-failed-only',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      api.post_check(
          post_process.MustRun,
          'Add a comment to the uprev CL (2).add comment on CL 123456'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results.chromeos-jacuzzi-chrome-skylab'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results (2).chromeos-jacuzzi-chrome-skylab'),
      status='FAILURE',
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          # Returns a failed pre-uprev test builder.
          PRE_UPREV_TEST_BUILDER_FAILED,
          # And a successful builder
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_test_retry_builds=[
          # Retry also failed
          PRE_UPREV_TEST_BUILDER_FAILED,
      ],
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_VALUES,
  )

  yield test(
      'retried-build-succeed',
      api.post_check(post_process.MustRun,
                     'Add a comment to the uprev CL.add comment on CL 123456'),
      api.post_check(
          post_process.MustRun,
          'Add a comment to the uprev CL (2).add comment on CL 123456'),
      api.post_process(
          post_process.StepFailure,
          'Process pre-uprev results.chromeos-jacuzzi-chrome-skylab'),
      api.post_process(
          post_process.StepSuccess,
          'Process pre-uprev results (2).chromeos-jacuzzi-chrome-skylab'),
      current_build=CURRENT_BUILD,
      pupr_generater_build_resps=[PUPR_GENERATOR_BUILD],
      uprev_test_builds=[
          # Returns a failed pre-uprev test builder.
          PRE_UPREV_TEST_BUILDER_FAILED,
          # And a successful builder
          PRE_UPREV_TEST_BUILDER_2,
      ],
      uprev_test_retry_builds=[
          # Retry succeeds
          PRE_UPREV_TEST_BUILDER_1,
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
      uprev_gerrit_change=UPREV_GERRIT_CHANGE_OVERRIDEN_VALUES,
  )

  # Fails if this build has less than 2 ancestor builds
  yield test(
      'invalid-current-task',
      status='FAILURE',
      # Invalid current build with less ancestor id
      current_build=build_pb2.Build(id=CURRENT_BUILD_ID, ancestor_ids=[99999]),
  )
