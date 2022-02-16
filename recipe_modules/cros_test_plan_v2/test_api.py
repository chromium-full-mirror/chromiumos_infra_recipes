# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.build.api.system_image import SystemImage
from PB.chromiumos.build.api.portage import Portage
from PB.chromiumos.config.api.design import Design
from PB.chromiumos.config.payload.flat_config import FlatConfigList, FlatConfig
from PB.chromiumos.test.api.dut_attribute import DutAttributeList, DutAttribute
from PB.chromiumos.test.api.coverage_rule import CoverageRule
from PB.chromiumos.test.api.v1.plan import HWTestPlan
from PB.chromiumos.test.plan.source_test_plan import SourceTestPlan
from PB.testplans.generate_test_plan import GenerateTestPlanResponse, HwTestUnit
from PB.testplans.target_test_requirements_config import HwTestCfg

BuildMetadata = SystemImage.BuildMetadata
BuildMetadataList = SystemImage.BuildMetadataList
BuildTarget = SystemImage.BuildTarget
TestPlanStarlarkFile = SourceTestPlan.TestPlanStarlarkFile


class CrosTestPlanV2TestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def kernel_source_test_plan():
    return SourceTestPlan(test_plan_starlark_files=[
        TestPlanStarlarkFile(
            host="chromium.googlesource.com",
            project="platform/testrepoA",
            path="a/b/kernel1.star",
        ),
        TestPlanStarlarkFile(
            host="chromium.googlesource.com",
            project="platform/testrepoB",
            path="kernel2.star",
        )
    ])

  @staticmethod
  def fp_source_test_plan():
    return SourceTestPlan(test_plan_starlark_files=[
        TestPlanStarlarkFile(
            host="chromium.googlesource.com",
            project="platform/testrepoB",
            path="dir/fp.star",
        )
    ])

  @staticmethod
  def build_metadata_list():
    return BuildMetadataList(values=[
        BuildMetadata(
            build_target=BuildTarget(
                portage_build_target=Portage.BuildTarget(
                    overlay_name='overlayA')))
    ])

  @staticmethod
  def flat_config_list():
    return FlatConfigList(values=[FlatConfig(hw_design=Design(name='design1'))])

  @staticmethod
  def dut_attribute_list():
    return DutAttributeList(
        dut_attributes=[DutAttribute(id=DutAttribute.Id(value='attribute1'))])

  @staticmethod
  def hw_test_plans():
    return [
        HWTestPlan(
            coverage_rules=[
                CoverageRule(name='kernel:4.4'),
                CoverageRule(name='kernel:5.2'),
            ],
        ),
        HWTestPlan(
            coverage_rules=[
                CoverageRule(name='wifiA'),
            ],
        ),
    ]

  @staticmethod
  def generate_test_plan_response():
    return GenerateTestPlanResponse(
        hw_test_units=[
            HwTestUnit(
                hw_test_cfg=HwTestCfg(
                    hw_test=[
                        HwTestCfg.HwTest(
                            skylab_board="boardA",
                        ),
                    ],
                ),
            )
        ],
    )
