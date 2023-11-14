# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from recipe_engine import recipe_test_api

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.test.api.provision_state import CompanionConfig
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TastGceTestCfg
from PB.testplans.target_test_requirements_config import TastTestShard
from PB.testplans.target_test_requirements_config import TastVmTestCfg
from PB.testplans.target_test_requirements_config import TestCompanion
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TastGceTestUnit
from PB.testplans.generate_test_plan import TastVmTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon


class CrosTestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for cros_test_plan api."""

  def test_unit_common(self, target_name='target', artifacts=None):
    common = TestUnitCommon(
        build_target=BuildTarget(name=target_name),
        build_payload=BuildPayload(
            artifacts_gs_bucket='chromeos-image-archive',
            artifacts_gs_path='target-cq/R12-3.4.5-6789',
        ),
        builder_name='test-builder',
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
        common=self.test_unit_common(target_name='another_target'),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(display_name='htarget.hw.bvt-inline',
                                           critical={'value': True}),
                    suite='bvt-inline',
                    skylab_board='another_target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.AUTOTEST,
                ),
            ],
        ),
    )

  @property
  def some_other_hw_test_unit(self):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(
                        display_name='htarget.hw.some-other-suite',
                        critical={'value': True}),
                    suite='some-other-suite',
                    skylab_board='target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.AUTOTEST,
                ),
            ],
        ),
    )

  def non_critical_hw_test_unit(self, suite_name='some-suite'):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(
                        display_name='htarget.hw.' + suite_name,
                        critical={'value': False}),
                    suite=suite_name,
                    skylab_board='target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.TAST,
                ),
            ],
        ),
    )

  @property
  def multi_dut_hw_test_unit(self, suite_name='multi-dut-suite'):
    return HwTestUnit(
        common=self.test_unit_common(),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(
                        display_name='htarget.hw.' + suite_name,
                        critical={'value': True}),
                    suite=suite_name,
                    skylab_board='target',
                    pool='my skylab pool',
                    hw_test_suite_type=HwTestCfg.TAST,
                    companions=[
                        TestCompanion(board="companiontarget"),
                        TestCompanion(
                            board="pixel7", config=CompanionConfig(
                                android=CompanionConfig.Android(
                                    gms_core_package="latest_stable"))),
                    ],
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
                    common=TestSuiteCommon(
                        display_name='ttarget.tast.sweet_shard_1_of_2',
                        critical={'value': True}), suite_name='tast-suite',
                    tast_test_expr=[
                        TastVmTestCfg.TastTestExpr(test_expr='!informational'),
                    ], tast_test_shard=TastTestShard(total_shards=2,
                                                     shard_index=0)),
                TastVmTestCfg.TastVmTest(
                    common=TestSuiteCommon(
                        display_name='ttarget.tast.sweet_shard_2_of_2',
                        critical={'value': True}), suite_name='tast-suite',
                    tast_test_expr=[
                        TastVmTestCfg.TastTestExpr(test_expr='!informational'),
                    ], tast_test_shard=TastTestShard(total_shards=2,
                                                     shard_index=1)),
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
                    common=TestSuiteCommon(
                        display_name='ttarget.tast.sweet-informational',
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
  def tast_gce_test_unit(self):
    return TastGceTestUnit(
        common=self.test_unit_common(),
        tast_gce_test_cfg=TastGceTestCfg(
            tast_gce_test=[
                TastGceTestCfg.TastGceTest(
                    common=TestSuiteCommon(
                        display_name='ttarget.tast_gce.sweet',
                        critical={'value': True}),
                    suite_name='tast-suite',
                    tast_test_expr=[
                        TastGceTestCfg.TastTestExpr(test_expr='!informational'),
                    ],
                    gce_metadata=TastGceTestCfg.TastGceTest.GceMetadata(
                        project='gce-test-project',
                        zone='us-west1-a',
                        machine_type='n2-standard-2',
                        network='gce-test-project-network',
                        subnet='us-west1-a',
                    ),
                ),
            ],
        ),
    )

  @property
  def tast_gce_informational_test_unit(self):
    return TastGceTestUnit(
        common=self.test_unit_common(),
        tast_gce_test_cfg=TastGceTestCfg(
            tast_gce_test=[
                TastGceTestCfg.TastGceTest(
                    common=TestSuiteCommon(
                        display_name='ttarget.tast_gce.sweet-informational',
                        critical={'value': False}),
                    suite_name='tast-suite-informational',
                    tast_test_expr=[
                        TastGceTestCfg.TastTestExpr(test_expr='informational'),
                    ],
                    gce_metadata=TastGceTestCfg.TastGceTest.GceMetadata(
                        project='gce-test-project',
                        zone='us-west1-a',
                        machine_type='n2-standard-2',
                        network='gce-test-project-network',
                        subnet='us-west1-a',
                    ),
                ),
            ],
        ),
    )

  @property
  def generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        hw_test_units=[
            self.hw_test_unit, self.another_hw_test_unit,
            self.some_other_hw_test_unit,
            self.non_critical_hw_test_unit()
        ],
        direct_tast_vm_test_units=[
            self.direct_tast_vm_test_unit, self.tast_vm_informational_test_unit
        ],
        tast_gce_test_units=[
            self.tast_gce_test_unit,
            self.tast_gce_informational_test_unit,
        ],
    )

  @property
  def all_non_critical_generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        hw_test_units=[
            self.non_critical_hw_test_unit('bvt-cq'),
            self.non_critical_hw_test_unit('bvt-inline'),
            self.non_critical_hw_test_unit('some-other-suite'),
        ],
        direct_tast_vm_test_units=[self.tast_vm_informational_test_unit],
        tast_gce_test_units=[self.tast_gce_informational_test_unit],
    )

  @property
  def reduced_criticality_generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        hw_test_units=[
            self.non_critical_hw_test_unit('bvt-cq'),
            self.non_critical_hw_test_unit('bvt-inline'),
        ],
        direct_tast_vm_test_units=[self.tast_vm_informational_test_unit],
    )
