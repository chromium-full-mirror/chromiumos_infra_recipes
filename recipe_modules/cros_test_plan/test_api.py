# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
from recipe_engine import recipe_test_api

from PB.chromiumos.common import BuildTarget
from PB.testplans.target_test_requirements_config import GceTestCfg
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import MoblabVmTestCfg
from PB.testplans.target_test_requirements_config import TastVmTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.target_test_requirements_config import VmTestCfg
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import GceTestUnit
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import MoblabVmTestUnit
from PB.testplans.generate_test_plan import TastVmTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.generate_test_plan import VmTestUnit


class CrosTestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for cros_test_plan api."""

  def test_unit_common(self, **kwargs):
    values = dict(
        build_target=BuildTarget(name='target'),
        build_payload=BuildPayload(
            artifacts_gs_bucket='gs://chromeos-image-archive',
            artifacts_gs_path='target-cq/R12-3.4.5-6789',
        ),
    )
    values.update(kwargs)
    return TestUnitCommon(**values)

  @property
  def gce_test_unit(self):
    return GceTestUnit(
        common=self.test_unit_common(),
        gce_test_cfg=GceTestCfg(
            gce_test=[
                GceTestCfg.GceTest(
                    common=TestSuiteCommon(display_name='gtarget.gce.gtest'),
                    test_type='gce',
                    test_suite='gce-test-suite',
                    timeout_sec=123,
                    use_ctest=True,
                ),
            ],),)

  @property
  def hw_test_unit(self):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(display_name='htarget.hw.bvt-cq'),
                    suite='bvt-cq',
                    skylab_board='target',
                    timeout_sec=123,
                    critical=True,
                    minimum_duts=2,
                    retry=True,
                    max_retries=3,
                    suite_min_duts=2,
                    offload_failures_only=True,
                ),
            ],),)

  @property
  def moblab_vm_test_unit(self):
    return MoblabVmTestUnit(
        common=self.test_unit_common(),
        moblab_vm_test_cfg=MoblabVmTestCfg(
            moblab_test=[
                MoblabVmTestCfg.MoblabTest(
                    common=TestSuiteCommon(display_name='mtarget.moblab.vm'),
                    test_type='moblab-vm',
                    timeout_sec=123,
                ),
            ],),)

  @property
  def tast_vm_test_unit(self):
    return TastVmTestUnit(
        common=self.test_unit_common(),
        tast_vm_test_cfg=TastVmTestCfg(
            tast_vm_test=[
                TastVmTestCfg.TastVmTest(
                    common=TestSuiteCommon(display_name='ttarget.tast.sweet'),
                    suite_name='tast-suite',
                    tast_test_expr=[
                        TastVmTestCfg.TastTestExpr(test_expr='exampe.Pass'),
                    ],
                    timeout_sec=123,
                ),
            ],),)

  @property
  def vm_test_unit(self):
    return VmTestUnit(
        common=self.test_unit_common(),
        vm_test_cfg=VmTestCfg(
            vm_test=[
                VmTestCfg.VmTest(
                    common=TestSuiteCommon(display_name='vtarget.vm.auto'),
                    test_type='vm_suite',
                    test_suite='autotest-suite',
                    timeout_sec=123,
                    retry=True,
                    max_retries=3,
                    use_ctest=True,
                ),
            ],),)

  @property
  def generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        gce_test_units=[self.gce_test_unit],
        hw_test_units=[self.hw_test_unit],
        moblab_vm_test_units=[self.moblab_vm_test_unit],
        tast_vm_test_units=[self.tast_vm_test_unit],
        vm_test_units=[self.vm_test_unit],
    )
