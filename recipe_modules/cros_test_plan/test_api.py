# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from recipe_engine import recipe_test_api

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TastVmTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.target_test_requirements_config import VmTestCfg
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TastVmTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.generate_test_plan import VmTestUnit


class CrosTestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for cros_test_plan api."""

  def test_unit_common(self, artifacts=None):
    common = TestUnitCommon(
        build_target=BuildTarget(name='target'),
        build_payload=BuildPayload(
            artifacts_gs_bucket='chromeos-image-archive',
            artifacts_gs_path='target-cq/R12-3.4.5-6789',
        ),
    )
    artifacts = artifacts or BuilderConfig.Artifacts.ArtifactTypes.values()
    for artifact in artifacts:
      artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
      common.build_payload.files_by_artifact.update({
          artifact_name: ['{}.txt'.format(artifact_name.lower())],
      })
    return common

  @property
  def hw_test_unit(self):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(display_name='htarget.hw.bvt-cq',
                                           critical={'value': True}),
                    suite='bvt-cq',
                    skylab_board='target',
                    skylab_model='model',
                    pool='DUT_POOL_QUOTA',
                    hw_test_suite_type=HwTestCfg.TAST,
                ),
            ],
        ),
    )

  @property
  def another_hw_test_unit(self):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(display_name='htarget.hw.bvt-inline',
                                           critical={'value': True}),
                    suite='bvt-inline',
                    skylab_board='target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.AUTOTEST,
                ),
            ],
        ),
    )

  @property
  def non_critical_hw_test_unit(self):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(display_name='htarget.hw.some-suite',
                                           critical={'value': False}),
                    suite='some-suite',
                    skylab_board='target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.TAST,
                ),
            ],
        ),
    )

  @property
  def direct_tast_vm_test_unit(self):
    return TastVmTestUnit(
        common=self.test_unit_common(),
        tast_vm_test_cfg=TastVmTestCfg(
            tast_vm_test=[
                TastVmTestCfg.TastVmTest(
                    common=TestSuiteCommon(display_name='ttarget.tast.sweet',
                                           critical={'value': True}),
                    suite_name='tast-suite',
                    tast_test_expr=[
                        TastVmTestCfg.TastTestExpr(test_expr='!informational'),
                    ],
                ),
            ],
        ),
    )

  @property
  def tast_vm_informational_test_unit(self):
    return TastVmTestUnit(
        common=self.test_unit_common(),
        tast_vm_test_cfg=TastVmTestCfg(
            tast_vm_test=[
                TastVmTestCfg.TastVmTest(
                    common=TestSuiteCommon(display_name='ttarget.tast.sweet',
                                           critical={'value': False}),
                    suite_name='tast-suite-informational',
                    tast_test_expr=[
                        TastVmTestCfg.TastTestExpr(test_expr='informational'),
                    ],
                ),
            ],
        ),
    )

  @property
  def vm_test_unit(self):
    return VmTestUnit(
        common=self.test_unit_common(),
        vm_test_cfg=VmTestCfg(
            vm_test=[
                VmTestCfg.VmTest(
                    common=TestSuiteCommon(display_name='vtarget.vm.auto',
                                           critical={'value': True}),
                    test_suite='autotest-suite',
                ),
            ],
        ),
    )

  @property
  def non_critical_vm_test_unit(self):
    return VmTestUnit(
        common=self.test_unit_common(),
        vm_test_cfg=VmTestCfg(
            vm_test=[
                VmTestCfg.VmTest(
                    common=TestSuiteCommon(
                        display_name='vtarget.vm.another-auto',
                        critical={'value': False}),
                    test_suite='another-autotest-suite',
                ),
            ],
        ),
    )

  @property
  def generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        hw_test_units=[
            self.hw_test_unit, self.another_hw_test_unit,
            self.non_critical_hw_test_unit
        ],
        direct_tast_vm_test_units=[
            self.direct_tast_vm_test_unit, self.tast_vm_informational_test_unit
        ],
        vm_test_units=[self.vm_test_unit, self.non_critical_vm_test_unit],
    )
