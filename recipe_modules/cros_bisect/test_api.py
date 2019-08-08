# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test responses for build API endpoints."""

from recipe_engine import recipe_test_api

from google.protobuf import json_format as jsonpb
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon

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

  def serialized_hw_test_unit(self, build_target_name):
    """Returns the JSON serialized version of a HwTestUnit.

    Args:
      build_target_name (str): the build target name.
    Returns:
      str: JSON serialized version of created HwTestUnit
    """
    tu = HwTestUnit(
        common=TestUnitCommon(build_target=BuildTarget(name=build_target_name)))
    return jsonpb.MessageToJson(tu)
