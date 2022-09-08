# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test responses for build API endpoints."""

from recipe_engine import recipe_test_api

from google.protobuf import json_format as jsonpb
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon


class CrosBisectTestApi(recipe_test_api.RecipeTestApi):

  def serialized_package_info(self, package, category, version):
    """Returns the JSON serialized version of a PackageInfo.

    Creates and returns the JSON serialized version of a PackageInfo cooked
    up from the given values.

    Args:
      package (str): the package name.
      category (str): the package category.
      version (str): the package version and revision.
    Returns:
      str: JSON serialized version of created PackageInfo
    """
    pi = PackageInfo(package_name=package, category=category, version=version)
    return jsonpb.MessageToJson(pi)

  def _hw_test_config(self, build_target_name):
    hw_test = HwTestCfg.HwTest(
        common=TestSuiteCommon(display_name='kip.hw.bvt-cq',
                               critical={'value': True}),
        suite='bvt-cq',
        skylab_board=build_target_name,
        pool='bisect test pool',
    )
    return HwTestCfg(hw_test=[hw_test])

  def hw_test_unit(self, build_target_name, hw_test_cfg=None):
    """Helper to create a HwTestUnit.

    Args:
      build_target_name (str): the build target name.
      hw_test_cfg (HwTestCfg): hardware test configuration to add, if any. If
          not provided a default is cooked up.
    Returns:
      HwTestUnit: created HwTestUnit.
    """
    hw_test_cfg = hw_test_cfg or self._hw_test_config(build_target_name)
    return HwTestUnit(
        common=TestUnitCommon(build_target=BuildTarget(name=build_target_name)),
        hw_test_cfg=hw_test_cfg,
    )

  def serialized_hw_test_unit(self, build_target_name, hw_test_cfg=None):
    """Returns the JSON serialized version of a HwTestUnit.

    Args:
      build_target_name (str): the build target name.
      hw_test_cfg (HwTestCfg): hardware test configuration to add, if any. If
          not provided a default is cooked up.
    Returns:
      str: JSON serialized version of created HwTestUnit
    """
    hw_test_unit = self.hw_test_unit(build_target_name, hw_test_cfg)
    return jsonpb.MessageToJson(hw_test_unit)

  def add_properties(self, build, build_target_name, gs_bucket='bucket',
                     gs_path='path', files_by_artifact=None):
    """Adds input/output properties expected for constructing a test plan.

    Adds the properties to `build` expected to be present in order to construct
    a test plan from a bisection invocation.

    Args:
      build (build_pb2.Build): build to add the properties to.
      build_target_name (str): the build target name.
      gs_bucket (str): artifacts google storage bucket.
      gs_path (str): artifacts google storage path.
      files_by_artifact (dict): files by artifact mapping.
    """
    build.input.properties['build_target'] = {
        'name': build_target_name,
    }
    files_by_artifact = files_by_artifact or {
        'IMAGE_ZIP': ['image.zip'],
        'TAST_FILES': ['tast1.zip', 'tast2.zip'],
    }
    build.output.properties['artifacts'] = {
        'gs_bucket': gs_bucket,
        'gs_path': gs_path,
        'files_by_artifact': files_by_artifact,
    }
