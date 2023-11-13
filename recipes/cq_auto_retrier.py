# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from collections import defaultdict
from typing import Generator
from typing import Optional

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import RetryDetails
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES
from RECIPE_MODULES.chromeos.auto_retry_util.api import CHROMEOS_LUCI_SERVICE_ACCOUNT

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'auto_retry_util',
    'easy',
    'future_utils',
    'gerrit',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  run_properties = defaultdict(lambda: 0)

  def _set_len_prop(**kwargs):
    """Helper function to set accumulating length of list properties."""
    for k, v in kwargs.items():
      run_properties[k] += len(v)

  builds = api.auto_retry_util.cq_retry_candidates()
  _set_len_prop(orch_builds_considered=builds)

  def _analyzing_candidate(b: build_pb2.Build) -> (Optional[RetryDetails]):
    with api.step.nest('analyzing %d' % b.id) as pres:
      retry_reason = RetryDetails(original_orch_id=b.id)

      pres.links['build link'] = api.buildbucket.build_url(build_id=b.id)

      # Examine builds.
      successful_builders, retryable_build_failures, outstanding_build_failures = api.auto_retry_util.analyze_build_failures(
          b)
      # TODO(b/299482781): When the retry infra failures experiment is active
      # the cq-orchestrator could be a retryable builder. Remove post-launch.
      if api.auto_retry_util.is_experimental_feature_enabled(
          EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES,
          b) and b.status == common.INFRA_FAILURE:
        retryable_build_failures.append(b.builder.builder)

      _set_len_prop(successful_builders=successful_builders,
                    retryable_build_failures=retryable_build_failures,
                    outstanding_build_failures=outstanding_build_failures)

      # Examine test suites.
      successful_test_suites, retryable_test_suite_failures, outstanding_test_suite_failures = api.auto_retry_util.analyze_test_results(
          b)
      _set_len_prop(
          successful_test_suites=successful_test_suites,
          retryable_test_suite_failures=retryable_test_suite_failures,
          outstanding_test_suite_failures=outstanding_test_suite_failures)

      # Examine exonerations.
      previously_exonerated, newly_exonerated, outstanding_exonerations = api.auto_retry_util.test_variant_exoneration_analysis(
          b)
      updated_failed_test_stats = previously_exonerated + newly_exonerated + outstanding_exonerations
      exonerated_test_suites = api.auto_retry_util.get_exonerated_suites(
          b, updated_failed_test_stats)
      _set_len_prop(previously_exonerated_tests=previously_exonerated,
                    newly_exonerated_tests=newly_exonerated,
                    outstanding_exonerations_tests=outstanding_exonerations,
                    exonerated_test_suites=exonerated_test_suites)

      retryable_test_suite_failures.extend(exonerated_test_suites)
      outstanding_test_suite_failures = list(
          set(outstanding_test_suite_failures) - set(exonerated_test_suites))

      attributed_test_suites = api.auto_retry_util.get_failure_attributed_hw_suites(
          b, already_retryable_suites=retryable_test_suite_failures)
      retryable_test_suite_failures.extend(attributed_test_suites)
      outstanding_test_suite_failures = list(
          set(outstanding_test_suite_failures) - set(attributed_test_suites))

      api.auto_retry_util.per_build_stats[
          b.id].retryable_test_suites = retryable_test_suite_failures
      api.auto_retry_util.per_build_stats[
          b.id].outstanding_test_suites = outstanding_test_suite_failures

      # Preliminary determination
      if len(outstanding_build_failures) == 0 and len(
          outstanding_test_suite_failures) == 0 and (
              retryable_build_failures or retryable_test_suite_failures):
        retry_reason.retryable_builders.extend(retryable_build_failures)
        retry_reason.retryable_test_suites.extend(retryable_test_suite_failures)
        retry_reason.experimental_features.extend(
            sorted(api.auto_retry_util.experimental_retries[b.id]))

        _set_len_prop(actionable_retryable_builders=retryable_build_failures,
                      actionable_test_suites=retry_reason.retryable_test_suites)
        return retry_reason
      api.auto_retry_util.per_build_stats[b.id].filter_reasons.append(
          'outstanding_failures')
      return None

  # A list of (Build, RetryDetails) tuples.
  retryable_runs = []

  with api.step.nest('analyzing candidates') as presentation:
    runner = api.future_utils.create_parallel_runner()
    for b in builds:
      runner.run_function_async(lambda build, _: _analyzing_candidate(build), b)
    responses = runner.wait_for_and_get_responses()
    retryable_runs.extend([(x.req, x.resp) for x in responses if x.resp])
    presentation.step_text = f'found {len(retryable_runs)} retryable run(s)'

  # Final determination
  filtered_runs = api.auto_retry_util.filter_retry_candidates(
      [run[0] for run in retryable_runs])
  retryable_runs = [run for run in retryable_runs if run[0] in filtered_runs]

  for b, retry_reason in retryable_runs:
    # Only call build_was_dry_run on builds that are actually retryable, since
    # it is possible the run mode property was not set on some candidates (
    # e.g. manually triggered builds). filter_retry_candidates should filter
    # builds where CV wasn't active, so we expect all retry candidates to have
    # the run mode property set at this point.
    retry_reason.original_orch_was_dry_run = api.auto_retry_util.build_was_dry_run(
        b)

  api.auto_retry_util.publish_per_build_stats()

  unthrottled_retry_n = len(retryable_runs)
  with api.step.nest('check recent executions for throttle'):
    retries_avail = api.auto_retry_util.unthrottled_retries_left()
    throttled_runs_n = max(unthrottled_retry_n - retries_avail, 0)
    run_properties['throttled_runs'] = throttled_runs_n

  # For now just slice the considered CL count somewhat arb (by query return
  # order), however in the future we might consider different methods of
  # prioritizing the cq runs to retry in a throttle constrained scenario.
  retryable_runs = retryable_runs[:retries_avail]

  unthrottled_retry_dry_run_n = len(
      [r for _, r in retryable_runs if r.original_orch_was_dry_run])
  summary = (f'{unthrottled_retry_n - unthrottled_retry_dry_run_n} CQ+2 run(s) '
             f'to retry, {unthrottled_retry_dry_run_n} CQ+1 run(s) to retry, '
             f'{throttled_runs_n} are throttled.')

  with api.step.nest('performing retries') as pres:
    pres.step_text = summary
    for b, details in retryable_runs:
      pres.links[f'{b.id}'] = api.buildbucket.build_url(build_id=b.id)
      # There should be at least one retryable builder or test suite at this
      # point, because cq_retry_candidates only returns builds with at least one
      # fatal failure, and there are no more outstanding failures for the build.
      api.auto_retry_util.retry_build(
          b,
          retryable_builders=details.retryable_builders,
          retryable_test_suites=details.retryable_test_suites,
      )
      details.retry_age_seconds = int(
          api.time.ms_since_epoch() / 1000) - b.end_time.seconds

  _set_len_prop(retries_made=retryable_runs)
  run_properties['retry_reasons'] = [
      json_format.MessageToDict(y) for x, y in retryable_runs
  ]

  api.easy.set_properties_step(run_properties=run_properties)
  return RawResult(status=common.SUCCESS, summary_markdown=summary)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  # An orchestrator with a retryable child build failure (builder1 is no longer
  # a CQ blocking builder).
  retryable_build_orch = api.test_util.test_orchestrator(
      cq=True,
      status='FAILURE',
      build_id=1111,
      create_time=1111,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      },
      output_properties={
          'has_child_failures':
              True,
          'child_build_info': [{
              'builder': {
                  'builder': 'builder1'
              },
              'status': 'FAILURE',
              'relevant': True,
              'collect_value': 'COLLECT'
          },]
      },
      tags={
          'cq_equivalent_cl_group_key': 'group_key1',
      },
  ).message

  retryable_build_orch_dry_run = build_pb2.Build()
  retryable_build_orch_dry_run.CopyFrom(retryable_build_orch)
  retryable_build_orch_dry_run.input.properties['$recipe_engine/cq'][
      'runMode'] = 'DRY_RUN'

  # An orchestrator with a retryable test failure (builder1 is no longer a CQ
  # blocking builder).
  retryable_test_orch = api.test_util.test_orchestrator(
      cq=True,
      status='FAILURE',
      build_id=1111,
      create_time=1111,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      },
      output_properties={
          'has_child_failures':
              True,
          'test_summary': [{
              'builder_name': 'builder1',
              'status': 'FAILURE',
              'critical': True,
              'name': 'builder1.hw.suite',
              'collect_value': 'COLLECT',
          },]
      },
      tags={
          'cq_equivalent_cl_group_key': 'group_key1',
      },
  ).message

  gerrit_changes = [
      common.GerritChange(change=123456,
                          host='chromium-review.googlesource.com', patchset=7)
  ]

  eligible_value_dict = {
      123456: {
          'change_number': 123456,
          'submittable': True,
          'host': 'test',
          'messages': [{
              'id':
                  '123' * 10,
              'author': {
                  '_account_id': 1234
              },
              'date':
                  '2022-09-26 19:59:27.000000000',
              'message':
                  'Patch Set 1:\n\nThis CL has failed the run. Reason: Tryjob [cq-orch](https://1111) failed',
              'tag':
                  'autogenerated:cq:full-run',
          }],
          'labels': {
              'Code-Review': {
                  'optional': True,
                  'all': [
                      {
                          '_account_id': 1234567,
                          'value': 0
                      },
                      {
                          '_account_id': 2345678,
                          'value': 2
                      },
                  ],
                  'values': {
                      ' 0': 'No score',
                      '+1': 'Looks good to me, but someone else must approve',
                      '+2': 'Looks good to me, approved',
                      '-1': 'I would prefer that you did not submit this',
                      '-2': 'Do not submit'
                  }
              },
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 0
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              },
          },
          'patch_set_revision': 'f000' * 10,
          'revision_info': {
              '_number': 1
          },
          'patch_set': 1,
      }
  }

  def retry_reason_has_experiment(check, step_odict, experiment: str):
    """Check that the retry_reasons property has an experimental feature.

    This check assumes that there is exactly one object in retry_reasons.

    Args:
        experiment: The experiment to look for in experimentalFeatures.

    Usage:
        yield(
            TEST,
            api.post_check(retry_reason_has_experiment, 'my-experiment'),
        )
    """
    build_properties = post_process.GetBuildProperties(step_odict)
    retry_reasons = build_properties['run_properties']['retry_reasons']
    if not check(f'expected exactly one retry_reason, got {retry_reasons}',
                 len(retry_reasons) == 1):
      return  # pragma: nocover
    retry_reason = retry_reasons[0]
    check(experiment in retry_reason['experimentalFeatures'])

  yield api.test(
      'retryable-build', api.auto_retry_util.enable_retries(),
      api.gerrit.set_get_account_id(
          gerrit_host='chromium-review.googlesource.com',
          email=CHROMEOS_LUCI_SERVICE_ACCOUNT, value=1234,
          parent_step_name='filter candidates.filter out unmet CL requirements'
      ),
      api.buildbucket.simulated_search_results(
          [retryable_build_orch],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'filter candidates.filter out unmet CL requirements', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build_orch.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'performing retries.retry build {retryable_build_orch.id}',
          gerrit_changes, eligible_value_dict,
          step_name=f'fetch changes for {retryable_build_orch.id}'),
      api.gerrit.set_get_change_mergeable(
          'filter candidates.filter out merge conflicts',
          gerrit_host='chromium-review.googlesource.com',
          change_num=123456,
          revision=7,
          value=True,
      ),
      api.post_process(
          post_process.MustRun,
          f'performing retries.retry build {retryable_build_orch.id}',
      ),
      api.post_process(
          post_process.LogEquals,
          f'performing retries.retry build {retryable_build_orch.id}',
          'retryable builders', 'builder1'),
      api.post_process(
          post_process.SummaryMarkdown,
          '1 CQ+2 run(s) to retry, 0 CQ+1 run(s) to retry, 0 are throttled.',
      ))

  yield api.test(
      'retryable-test', api.auto_retry_util.enable_retries(),
      api.gerrit.set_get_account_id(
          gerrit_host='chromium-review.googlesource.com',
          email=CHROMEOS_LUCI_SERVICE_ACCOUNT, value=1234,
          parent_step_name='filter candidates.filter out unmet CL requirements'
      ),
      api.buildbucket.simulated_search_results(
          [retryable_test_orch],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'filter candidates.filter out unmet CL requirements', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_test_orch.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'performing retries.retry build {retryable_test_orch.id}',
          gerrit_changes, eligible_value_dict,
          step_name=f'fetch changes for {retryable_test_orch.id}'),
      api.gerrit.set_get_change_mergeable(
          'filter candidates.filter out merge conflicts',
          gerrit_host='chromium-review.googlesource.com',
          change_num=123456,
          revision=7,
          value=True,
      ),
      api.post_process(
          post_process.MustRun,
          f'performing retries.retry build {retryable_test_orch.id}',
      ),
      api.post_process(
          post_process.LogEquals,
          f'performing retries.retry build {retryable_test_orch.id}',
          'retryable test suites', 'builder1.hw.suite'),
      api.post_process(
          post_process.SummaryMarkdown,
          '1 CQ+2 run(s) to retry, 0 CQ+1 run(s) to retry, 0 are throttled.',
      ))

  yield api.test(
      'retryable-dry-run',
      api.auto_retry_util.enable_retries(),
      api.gerrit.set_get_account_id(
          gerrit_host='chromium-review.googlesource.com',
          email=CHROMEOS_LUCI_SERVICE_ACCOUNT, value=1234,
          parent_step_name='filter candidates.filter out unmet CL requirements'
      ),
      api.buildbucket.simulated_search_results(
          [retryable_build_orch_dry_run],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'filter candidates.filter out unmet CL requirements', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build_orch.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'performing retries.retry build {retryable_build_orch.id}',
          gerrit_changes, eligible_value_dict,
          step_name=f'fetch changes for {retryable_build_orch.id}'),
      api.gerrit.set_get_change_mergeable(
          'filter candidates.filter out merge conflicts',
          gerrit_host='chromium-review.googlesource.com',
          change_num=123456,
          revision=7,
          value=True,
      ),
      api.post_process(
          post_process.MustRun,
          f'performing retries.retry build {retryable_build_orch.id}',
      ),
      api.post_process(
          post_process.LogEquals,
          f'performing retries.retry build {retryable_build_orch.id}',
          'retryable builders', 'builder1'),
      api.post_process(
          post_process.SummaryMarkdown,
          '0 CQ+2 run(s) to retry, 1 CQ+1 run(s) to retry, 0 are throttled.',
      ),
      api.post_process(post_process.DropExpectation),
  )

  retryable_orch_build = api.test_util.test_orchestrator(
      cq=True,
      status='INFRA_FAILURE',
      build_id=1111,
      create_time=1111,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      },
      output_properties={
          'has_child_failures': False,
      },
      experiments=['chromeos.auto_retry_util.retry_infra_failures'],
      tags={
          'cq_equivalent_cl_group_key': 'group_key1',
      },
  ).message

  yield api.test(
      'retryable-orchestrator-exp-feature',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(
                      enable_retries=True, experimental_features=[
                          ExperimentalFeature(
                              name=EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES,
                              experiment_flag='chromeos.auto_retry_util.retry_infra_failures'
                          )
                      ])
          }),
      api.gerrit.set_get_account_id(
          gerrit_host='chromium-review.googlesource.com',
          email=CHROMEOS_LUCI_SERVICE_ACCOUNT, value=1234,
          parent_step_name='filter candidates.filter out unmet CL requirements'
      ),
      api.buildbucket.simulated_search_results(
          [retryable_orch_build],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'filter candidates.filter out unmet CL requirements', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_orch_build.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'performing retries.retry build {retryable_orch_build.id}',
          gerrit_changes, eligible_value_dict,
          step_name=f'fetch changes for {retryable_orch_build.id}'),
      api.gerrit.set_get_change_mergeable(
          'filter candidates.filter out merge conflicts',
          gerrit_host='chromium-review.googlesource.com',
          change_num=123456,
          revision=7,
          value=True,
      ),
      api.post_process(
          post_process.MustRun,
          f'performing retries.retry build {retryable_orch_build.id}',
      ),
      api.post_process(
          post_process.LogEquals,
          f'performing retries.retry build {retryable_orch_build.id}',
          'retryable builders', 'cq-orchestrator'),
      api.post_check(retry_reason_has_experiment, 'retry-infra-failures'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'retryable-orchestrator-exp-feature-not-enabled',
      api.auto_retry_util.enable_retries(),
      api.buildbucket.simulated_search_results(
          [retryable_orch_build],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.DoesNotRun,
          f'performing retries.retry build {retryable_orch_build.id}',
      ),
      api.post_process(post_process.DropExpectation),
  )

  orch_build = api.test_util.test_orchestrator(
      cq=True,
      status='FAILURE',
      build_id=1111,
      create_time=1111,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      },
      output_properties={
          'has_child_failures': True,
      },
      experiments=['chromeos.auto_retry_util.retry_infra_failures'],
      tags={
          'cq_equivalent_cl_group_key': 'group_key1',
      },
  ).message

  # This test case was added due to an edge case where child_build_info did not
  # correctly report the status and relevance of the child builds due to a
  # failure in the buildbucket.search() call (b/303105163).
  yield api.test(
      'no-outstanding-failures-reported-no-retryable',
      api.auto_retry_util.enable_retries(),
      api.buildbucket.simulated_search_results(
          [orch_build],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.DoesNotRun,
          f'performing retries.retry build {orch_build.id}',
      ),
      api.post_check(lambda check, steps: check(steps[
          'set per_build_stats'].output_properties['per_build_stats'][0][
              'filter_reasons'] == ['outstanding_failures'])),
      api.post_process(post_process.DropExpectation),
  )
