# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from typing import Generator
from typing import Optional

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'auto_retry_util',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  builds = api.auto_retry_util.cq_retry_candidates()
  # While we decide on the retry critera start by retrying only runs which have
  # no outstanding failures.
  no_outstanding_failure_runs = []
  with api.step.nest('analyzing candidates'):
    for b in builds:
      with api.step.nest('analyzing %d' % b.id) as pres:
        pres.links['build link'] = api.buildbucket.build_url(build_id=b.id)
        _, _, outstanding_build_failures = api.auto_retry_util.analyze_build_failures(
            b)
        _, _, outstanding_test_suite_failures = api.auto_retry_util.analyze_test_results(
            b)
        prev_exon, newly_exon, outstanding = api.auto_retry_util.test_variant_exoneration_analysis(
            b)
        updated_failed_test_stats = prev_exon + newly_exon + outstanding
        exonerated_test_suites = api.auto_retry_util.get_exonerated_suites(
            b, updated_failed_test_stats)
        outstanding_test_suite_failures = list(
            set(outstanding_test_suite_failures) - set(exonerated_test_suites))

        if len(outstanding_build_failures) == 0 and len(
            outstanding_test_suite_failures) == 0:
          no_outstanding_failure_runs.append(b)

  summary = f'found {len(no_outstanding_failure_runs)} run(s) to retry.'
  with api.step.nest('performing retries') as pres:
    pres.step_text = summary
    # TODO(b/294075301): Add method to act on CLs. For now just list them so we
    # can inspect them manually.
    for b in no_outstanding_failure_runs:
      pres.links[f'{b.id}'] = api.buildbucket.build_url(build_id=b.id)

  return RawResult(status=common.SUCCESS, summary_markdown=summary)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  cq_orchs = [
      api.test_util.test_orchestrator(cq=True, status='FAILURE', build_id=1111,
                                      create_time=1111).message,
      api.test_util.test_orchestrator(cq=True, status='FAILURE', build_id=1112,
                                      create_time=1112).message,
  ]
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          cq_orchs, 'query for cq-orchestrators.buildbucket.search'),
  )
