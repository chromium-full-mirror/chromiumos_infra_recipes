# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from collections import defaultdict
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'auto_retry_util',
    'easy',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  run_properties = defaultdict(lambda: 0)

  builds = api.auto_retry_util.cq_retry_candidates()
  run_properties.update({'orch_builds_considered': len(builds)})

  # While we decide on the retry critera start by retrying only runs which have
  # no outstanding failures.
  retryable_runs = []

  # Maps of build id -> retryable builds / tests.
  build_to_retryable_build_failures: Dict[int, List[str]] = {}
  build_to_exonerated_test_suites: Dict[int, List[str]] = {}
  with api.step.nest('analyzing candidates'):
    for b in builds:
      with api.step.nest('analyzing %d' % b.id) as pres:
        pres.links['build link'] = api.buildbucket.build_url(build_id=b.id)

        # Examine builds.
        _, retryable_build_failures, outstanding_build_failures = api.auto_retry_util.analyze_build_failures(
            b)
        run_properties['retryable_build_failures'] += len(
            retryable_build_failures)
        run_properties['outstanding_build_failures'] += len(
            outstanding_build_failures)

        # Examine test suites.
        _, retryable_test_suite_failures, outstanding_test_suite_failures = api.auto_retry_util.analyze_test_results(
            b)
        run_properties['retryable_test_suite_failures'] += len(
            retryable_test_suite_failures)
        run_properties['outstanding_test_suite_failures'] += len(
            outstanding_test_suite_failures)

        # Examine exonerations.
        previously_exonerated, newly_exonerated, outstanding_exonerations = api.auto_retry_util.test_variant_exoneration_analysis(
            b)
        run_properties['previously_exonerated_tests'] += len(
            previously_exonerated)
        run_properties['newly_exonerated_tests'] += len(newly_exonerated)
        run_properties['outstanding_exonerations_tests'] += len(
            outstanding_exonerations)

        updated_failed_test_stats = previously_exonerated + newly_exonerated + outstanding_exonerations
        exonerated_test_suites = api.auto_retry_util.get_exonerated_suites(
            b, updated_failed_test_stats)
        run_properties['exonerated_test_suites'] += len(exonerated_test_suites)

        outstanding_test_suite_failures = list(
            set(outstanding_test_suite_failures) - set(exonerated_test_suites))

        # Final determination.
        if len(outstanding_build_failures) == 0 and len(
            outstanding_test_suite_failures) == 0:
          retryable_runs.append(b)
          build_to_retryable_build_failures[b.id] = retryable_build_failures
          build_to_exonerated_test_suites[
              b.id] = exonerated_test_suites + retryable_test_suite_failures

  unthrottled_retry_n = len(retryable_runs)
  with api.step.nest('check recent executions for throttle'):
    retries_avail = api.auto_retry_util.unthrottled_retries_left()
    throttled_runs_n = max(unthrottled_retry_n - retries_avail, 0)
    run_properties['throttled_runs'] = throttled_runs_n

  # For now just slice the considered CL count somewhat arb (by query return
  # order), however in the future we might consider different methods of
  # prioritizing the cq runs to retry in a throttle constrained scenario.
  retryable_runs = retryable_runs[:retries_avail]

  summary = f'{unthrottled_retry_n} run(s) to retry, {throttled_runs_n} are throttled.'

  with api.step.nest('performing retries') as pres:
    pres.step_text = summary
    for b in retryable_runs:
      pres.links[f'{b.id}'] = api.buildbucket.build_url(build_id=b.id)
      # There should be at least one retryable builder or test suite at this
      # point, because cq_retry_candidates only returns builds with at least one
      # fatal failure, and there are no more outstanding failures for the build.
      api.auto_retry_util.retry_build(
          b,
          retryable_builders=build_to_retryable_build_failures[b.id],
          retryable_test_suites=build_to_exonerated_test_suites[b.id],
      )
  run_properties['retries_made'] = len(retryable_runs)

  api.easy.set_properties_step(run_properties=run_properties)
  return RawResult(status=common.SUCCESS, summary_markdown=summary)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  # An orchestrator with a retryable child build failure (builder1 is no longer
  # a CQ blocking builder).
  retryable_build_orch = api.test_util.test_orchestrator(
      cq=True, status='FAILURE', build_id=1111, create_time=1111,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      }, output_properties={
          'has_child_failures':
              True,
          'child_build_info': [{
              'builder': {
                  'builder': 'builder1'
              },
              'status': 'FAILURE',
              'relevant': True
          },]
      }).message

  # An orchestrator with a retryable test failure (builder1 is no longer a CQ
  # blocking builder).
  retryable_test_orch = api.test_util.test_orchestrator(
      cq=True, status='FAILURE', build_id=1112, create_time=1112,
      input_properties={
          '$recipe_engine/cq': {
              'runMode': 'FULL_RUN'
          }
      }, output_properties={
          'has_child_failures':
              True,
          'test_summary': [{
              'builder_name': 'builder1',
              'status': 'FAILURE',
              'critical': True,
              'name': 'builder1.hw.suite'
          },]
      }).message

  yield api.test(
      'retryable-build',
      api.auto_retry_util.enable_retries(),
      api.buildbucket.simulated_search_results(
          [retryable_build_orch],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.MustRun,
          'performing retries.retry build 1111',
      ),
      api.post_process(post_process.LogEquals,
                       'performing retries.retry build 1111',
                       'retryable builders', 'builder1'),
  )

  yield api.test(
      'retryable-test',
      api.auto_retry_util.enable_retries(),
      api.buildbucket.simulated_search_results(
          [retryable_test_orch],
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.MustRun,
          'performing retries.retry build 1112',
      ),
      api.post_process(post_process.LogEquals,
                       'performing retries.retry build 1112',
                       'retryable test suites', 'builder1.hw.suite'),
  )
