# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from collections import defaultdict
from typing import Generator
from typing import Optional

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import RetryDetails

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'recipe_engine/time',
    'auto_retry_util',
    'easy',
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

  # A list of (Build, RetryDetails) tuples.
  retryable_runs = []

  with api.step.nest('analyzing candidates'):
    for b in builds:
      with api.step.nest('analyzing %d' % b.id) as pres:
        retry_reason = RetryDetails(original_orch_id=b.id)

        pres.links['build link'] = api.buildbucket.build_url(build_id=b.id)

        # Examine builds.
        successful_builders, retryable_build_failures, outstanding_build_failures = api.auto_retry_util.analyze_build_failures(
            b)
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

        outstanding_test_suite_failures = list(
            set(outstanding_test_suite_failures) - set(exonerated_test_suites))

        # Final determination.
        if len(outstanding_build_failures) == 0 and len(
            outstanding_test_suite_failures) == 0:
          retry_reason.retryable_builders.extend(retryable_build_failures)
          retry_reason.retryable_test_suites.extend(
              retryable_test_suite_failures + exonerated_test_suites)
          retryable_runs.append((b, retry_reason))
          _set_len_prop(
              actionable_retryable_builders=retryable_build_failures,
              actionable_test_suites=retry_reason.retryable_test_suites)

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
