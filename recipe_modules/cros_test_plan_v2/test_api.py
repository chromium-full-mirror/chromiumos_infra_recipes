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
from PB.chromiumos.test.plan.source_test_plan import SourceTestPlan

BuildMetadata = SystemImage.BuildMetadata
BuildMetadataList = SystemImage.BuildMetadataList
BuildTarget = SystemImage.BuildTarget
Requirements = SourceTestPlan.Requirements


class CrosTestPlanV2TestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def kernel_source_test_plan():
    return SourceTestPlan(
        requirements=Requirements(
            kernel_versions=Requirements.KernelVersions(),
        ),
    )

  @staticmethod
  def fp_source_test_plan():
    return SourceTestPlan(
        requirements=Requirements(
            fingerprint=Requirements.Fingerprint(),
        ),
    )

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
  def coverage_rules():
    return [
        CoverageRule(name='kernel:4.4'),
        CoverageRule(name='kernel:5.2'),
    ]
