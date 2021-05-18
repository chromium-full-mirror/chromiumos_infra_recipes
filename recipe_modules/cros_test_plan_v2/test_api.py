# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.chromiumos.test.api.coverage_rule import CoverageRule
from PB.chromiumos.test.api.dut_attribute import (DutAttribute, DutCriterion)
from PB.chromiumos.test.api.test_suite import TestSuite


class CrosTestPlanV2TestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def kernel_coverage_rule():
    return CoverageRule(
        name='kernel:5.4',
        test_suites=[
            TestSuite(
                test_case_tag_criteria=TestSuite.TestCaseTagCriteria(
                    tags=['kernel']),
            ),
        ],
        dut_criteria=[
            DutCriterion(
                attribute_id=DutAttribute.Id(value='kernel_id'),
                values=['5.4'],
            )
        ],
    )

  @staticmethod
  def fp_coverage_rule():
    return CoverageRule(
        name='fp:present',
        test_suites=[
            TestSuite(
                test_case_tag_criteria=TestSuite.TestCaseTagCriteria(
                    tag_excludes=['flaky']),
            ),
        ],
        dut_criteria=[
            DutCriterion(
                attribute_id=DutAttribute.Id(value='fingerprint'),
                values=['PRESENT'],
            )
        ],
    )
