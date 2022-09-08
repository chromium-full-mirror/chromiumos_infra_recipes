# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with FindIt."""

import collections

from google.protobuf import json_format as jsonpb

from PB.chromiumos.common import PackageInfo
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.target_test_requirements_config import HwTestCfg

from recipe_engine import recipe_api


class CrosBisectApi(recipe_api.RecipeApi):
  """A module for interacting with FindIt."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosBisectApi, self).__init__(*args, **kwargs)
    self._compile = properties.compile
    self._test = properties.test
    self._test_bisection_percent = properties.test_bisection_percent
    self._test_bisection_count = properties.test_bisection_count

  def _set_bisect_builder(self, builder):
    self.m.easy.set_properties_step(BISECT_BUILDER=builder)

  def set_bisect_builder(self, build_target_name):
    """Sets the BISECT_BUILDER output property for the build target recipe.

    Sets the BISECT_BUILDER output property to the name of the builder FindIt
    should invoke if the build fails and bisection is required.

    Args:
      build_target_name (str): build target name to set the bisect builder for.
    """
    self._set_bisect_builder(build_target_name + '-bisect')

  def set_orchestrator_bisect_builder(self):
    """Sets the BISECT_BUILDER output property for the orchestrator.

    Sets the BISECT_BUILDER output property to the name of the builder FindIt
    should invoke if the postsubmit-orchestrator encounters hardware test
    failures.
    """
    self._set_bisect_builder('bisecting-orchestrator')

  def get_packages(self):
    """Returns packages to build as specified by FindIt or empty list.

    Returns the packages to build as specified by a FindIt invocation or an
    empty list if this run was not invoked as a bisection build.

    Returns:
      list[PackageInfo]: list of packages to build as specified by FindIt
    """
    return [jsonpb.Parse(t, PackageInfo()) for t in self._compile.targets]

  def get_test_child_builders(self):
    """Returns the child builders as specified by FindIt or empty list.

    Returns the child builders that need to run as specified by a FindIt
    invocation or an empty list if this run was not invoked as a bisection
    build.

    Returns:
      list[str]: sorted list of child builders to run.
    """
    child_builders = set()
    for failure in self._test.hw_test_failures:
      hw_test_unit = jsonpb.Parse(failure.test_spec, HwTestUnit())
      child_builders.add(hw_test_unit.common.build_target.name + '-postsubmit')
    return sorted(child_builders)

  def get_test_plan(self, builds):
    """Returns the test plan as specified by FindIt or None.

    Returns the test plan that needs to run as specified by a FindIt
    invocation or None if this run was not invoked as a bisection build.

    Args:
      builds (list[build_pb2.Build]): list of completed builds. While FindIt
          has returned the test plan to run the TestUnitCommon.BuildPayloads
          in that plan need to be updated for this bisection invocation. The
          information to do that update is retrieved from these builds.

    Returns:
      GenerateTestPlanResponse or None.
    """
    # These were split out into separate units so that each test failure could
    # travel with the suite that failed for FindIt (for grouping). Here we put
    # them back together again for the response.
    hw_test_units = collections.defaultdict(list)
    for failure in self._test.hw_test_failures:
      hw_test_unit = jsonpb.Parse(failure.test_spec, HwTestUnit())
      # Protocol messages aren't hashable, so we use a json serialized
      # conversion for the key while grouping.
      key = jsonpb.MessageToJson(hw_test_unit.common)
      hw_test_units[key].append(hw_test_unit)
    if not hw_test_units:  # pragma: no cover
      return None

    build_payloads = {}
    failures = []
    for build in builds:
      try:
        build_target_name = build.input.properties['build_target']['name']
        artifacts = build.output.properties['artifacts']
        build_payload = BuildPayload(
            artifacts_gs_bucket=artifacts['gs_bucket'],
            artifacts_gs_path=artifacts['gs_path'],
            files_by_artifact=artifacts['files_by_artifact'],
        )
        build_payloads[build_target_name] = build_payload
      except ValueError as ex:  # pragma: no cover
        # Save any exception that occurred so we can log it properly later.
        failures.append(ex)

    response = GenerateTestPlanResponse()
    for _, units in hw_test_units.items():
      # This is the TestUnitCommon from the failed invocation. Here we update
      # the BuildPayload for the builds we are bisecting on.
      test_unit_common = units[0].common
      build_target_name = test_unit_common.build_target.name
      build_payload = build_payloads.get(build_target_name, None)
      if not build_payload:  # pragma: no cover
        msg = 'Unable to resolve a BuildPayload for {}.'.format(
            build_target_name,
        )

        if failures:
          msg += "\n"
          msg += "Saw one or more failures querying BuildPayloads:\n"
          for failure in failures:
            msg += str(failure) + "\n"

        raise ValueError(msg)

      test_unit_common.build_payload.CopyFrom(build_payload)
      hw_test_unit = HwTestUnit(common=test_unit_common)
      hw_test_cfg = HwTestCfg()
      for unit in units:
        hw_test_cfg.hw_test.extend(unit.hw_test_cfg.hw_test)
      hw_test_unit.hw_test_cfg.CopyFrom(hw_test_cfg)
      response.hw_test_units.extend([hw_test_unit])
    return response
