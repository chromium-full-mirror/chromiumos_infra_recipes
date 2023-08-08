# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from typing import Generator
from typing import Optional

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
  with api.step.nest('analyzing candidates'):
    for b in builds:
      with api.step.nest('analyzing %d' % b.id) as pres:
        pres.links['build link'] = api.buildbucket.build_url(build_id=b.id)
        _, _, _ = api.auto_retry_util.analyze_build_failures(b)
        _, _, _ = api.auto_retry_util.analyze_test_results(b)
        # TODO(b/291768475): Try exonerating suites using the updated
        # exoneration configs.
        prev_exon, newly_exon, outstanding = api.auto_retry_util.test_variant_exoneration_analysis(
            b)
        updated_failed_test_stats = prev_exon + newly_exon + outstanding
        _ = api.auto_retry_util.get_exonerated_suites(
            b, updated_failed_test_stats)


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
