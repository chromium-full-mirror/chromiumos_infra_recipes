# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Mocks for testing the cros_test_plan module."""

from typing import Any, Dict

from google.protobuf import json_format

from recipe_engine import recipe_test_api
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon


class CrosCqAdditionalTestsTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for cros_test_plan api."""

  @staticmethod
  def generate_mock_artifact(build_target: str = 'target') -> Dict[str, Any]:
    """Create a mock artifact for use in testing."""
    artifact = {}
    artifact['gs_bucket'] = 'chromeos-image-archive'
    artifact['gs_path'] = build_target + '-cq/R12-3.4.5-6789'
    files = {}
    for a in BuilderConfig.Artifacts.ArtifactTypes.values():
      a_name = BuilderConfig.Artifacts.ArtifactTypes.Name(a)
      files.update({
          a_name: ['{}.txt'.format(a_name.lower())],
      })
    artifact['files_by_artifact'] = files
    return artifact

  def test_unit_common(self, build_target='target'):
    artifact = self.generate_mock_artifact(build_target=build_target)
    t_common = TestUnitCommon(
        build_target=BuildTarget(name=build_target),
        build_payload=BuildPayload(
            artifacts_gs_bucket=artifact['gs_bucket'],
            artifacts_gs_path=artifact['gs_path'],
        ),
        builder_name=build_target + '-cq',
    )
    for artifact_name in artifact['files_by_artifact'].keys():
      t_common.build_payload.files_by_artifact.update({
          artifact_name: artifact['files_by_artifact'][artifact_name],
      })

    return t_common

  def generate_mock_test_suite(self, test_suite='suite', board='board',
                               build_target='build_target',
                               pool='DUT_POOL_QUOTA', critical=False):
    return HwTestUnit(
        common=self.test_unit_common(build_target),
        hw_test_cfg=HwTestCfg(
            hw_test=[
                HwTestCfg.HwTest(
                    common=TestSuiteCommon(
                        display_name=build_target + '.hw.' + test_suite,
                        critical={'value': critical}),
                    suite=test_suite,
                    skylab_board=board,
                    pool=pool,
                    hw_test_suite_type=HwTestCfg.TAST,
                    run_via_cft=True,
                ),
            ],
        ),
    )

  @property
  def generate_test_plan_response(self):
    return GenerateTestPlanResponse(
        hw_test_units=[
            self.generate_mock_test_suite(critical=True),
            self.generate_mock_test_suite(test_suite='somesuite',
                                          board='someboard',
                                          build_target='some_build_target'),
        ],
    )

  @property
  def generate_mock_build(self):
    return self._create_build_input_object(
        ['build_target', 'some_build_target', 'mybuild'])

  def _create_build_input_object(self, build_targets):
    builds = []
    for bt in build_targets:
      properties = {}
      properties = {'artifacts': self.generate_mock_artifact(build_target=bt)}

      output = Build.Output()
      output.properties.update(properties)
      build = Build(id=1234, builder={'builder': bt + '-cq'},
                    status=common.SUCCESS, output=output)

      build.input.properties.update(
          {'buildTarget': json_format.MessageToDict(BuildTarget(name=bt))})
      builds.append(build)
    return builds

  @property
  def generate_mock_gerrit_change(self):
    return [
        GerritChange(host='chrome-internal-review.googlesource.com',
                     project='p1', change=1235)
    ]
