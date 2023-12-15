# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.build.api.system_image import SystemImage
from PB.chromiumos.build.api.portage import Portage
from PB.chromiumos.builder_config import BuilderConfigs, BuilderConfig
from PB.chromiumos.config.api.design import Design
from PB.chromiumos.config.payload.config_bundle import ConfigBundleList, ConfigBundle
from PB.chromiumos.test.api.dut_attribute import DutAttributeList, DutAttribute
from PB.chromiumos.test.api.coverage_rule import CoverageRule
from PB.chromiumos.test.api.v1.plan import HWTestPlan
from PB.chromiumos.test.plan.source_test_plan import SourceTestPlan
from PB.testplans.board_priorities import BoardPriorityList, BoardPriority

PYTHON_VERSION_COMPATIBILITY = 'PY3'

BuildMetadata = SystemImage.BuildMetadata
BuildMetadataList = SystemImage.BuildMetadataList
BuildTarget = SystemImage.BuildTarget
TestPlanStarlarkFile = SourceTestPlan.TestPlanStarlarkFile


class CrosTestPlanV2TestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def kernel_source_test_plan():
    return SourceTestPlan(test_plan_starlark_files=[
        TestPlanStarlarkFile(
            host='chromium.googlesource.com',
            project='platform/testrepoA',
            path='a/b/kernel1.star',
        ),
        TestPlanStarlarkFile(
            host='chromium.googlesource.com',
            project='platform/testrepoB',
            path='kernel2.star',
        )
    ])

  @staticmethod
  def fp_source_test_plan():
    return SourceTestPlan(test_plan_starlark_files=[
        TestPlanStarlarkFile(
            host='chromium.googlesource.com',
            project='platform/testrepoB',
            path='dir/fp.star',
        )
    ])

  @staticmethod
  def fallback_default_source_test_plan():
    return SourceTestPlan(test_plan_starlark_files=[
        TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_tast_hw.star',
        ),
        TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_autotest_hw.star',
        ),
        TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_vm.star',
        ),
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
  def config_bundle_list():
    return ConfigBundleList(
        values=[ConfigBundle(design_list=[Design(name='design1')])])

  @staticmethod
  def dut_attribute_list():
    return DutAttributeList(
        dut_attributes=[DutAttribute(id=DutAttribute.Id(value='attribute1'))])

  @staticmethod
  def board_priority_list():
    return BoardPriorityList(board_priorities=[
        BoardPriority(
            skylab_board='testboardA',
            priority=-100,
        )
    ])

  @staticmethod
  def builder_configs():
    return BuilderConfigs(builder_configs=[
        BuilderConfig(
            id=BuilderConfig.Id(name='testboardA-cq'),
        )
    ])

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

  def generate_test_plan_response(self):
    return self.m.cros_test_plan.generate_test_plan_response
