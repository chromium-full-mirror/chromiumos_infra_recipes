# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import duration_pb2

from PB.chromiumos.test.api import test_suite as ctr_test_suite
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_plan',
    'git_footers',
    'metadata',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  def uht(builder_name, suite):
    hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
    hw_test_unit.common.builder_name = builder_name
    hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
    hw_test.common.display_name = '%s.hw.%s' % (builder_name, suite)
    hw_test.suite = suite
    hw_test.run_via_cft = True
    hw_test.run_via_trv2 = True
    hw_test.tag_criteria.CopyFrom(
        ctr_test_suite.TestSuite.TestCaseTagCriteria(
            tags=["include_this_tag_1", "include_this_tag_2"],
            tag_excludes=["exclude_this_tag_1", "exclude_this_tag_2"],
            test_names=['include_this_test'],
            test_name_excludes=['exlude_this_test']))
    return UnitHwTest(
        unit=hw_test_unit,
        hw_test=hw_test,
    )

  _ = api.skylab.schedule_suites(
      [
          uht('a-cq', 'bvt-tast-cq'),
          uht('b-cq', 'tast-tags-test-suite'),
          uht('c-cq', 'bvt-tast-cq-hw'),
      ],
      timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(target="target"),
  )


def GenTests(api):
  # Only schedules the tast-tags-test-suite with tagCriteria.
  yield api.test(
      'not-elegible',
      api.buildbucket.ci_build(),
      api.post_check(lambda check, steps: check('tagCriteria' not in steps[
          'schedule skylab tests v2.create test requests.configure a-cq'].logs[
              'request'])),
      api.post_check(lambda check, steps: check('tagCriteria' not in steps[
          'schedule skylab tests v2.create test requests.configure c-cq'].logs[
              'request'])),
      api.post_check(lambda check, steps: check('tagCriteria' in steps[
          'schedule skylab tests v2.create test requests.configure b-cq'].logs[
              'request'])),
  )

  # Schedules both bvt-tast-cq and tast-tags-test-suite with tagCriteria.
  yield api.test(
      'elegible',
      api.buildbucket.ci_build(
          experiments=['chromeos.skylab.direct_tast_testing']),
      api.post_check(lambda check, steps: check('tagCriteria' in steps[
          'schedule skylab tests v2.create test requests.configure a-cq'].logs[
              'request'])),
      api.post_check(lambda check, steps: check('tagCriteria' in steps[
          'schedule skylab tests v2.create test requests.configure b-cq'].logs[
              'request'])),
      api.post_check(lambda check, steps: check('tagCriteria' in steps[
          'schedule skylab tests v2.create test requests.configure b-cq'].logs[
              'request'])),
  )
