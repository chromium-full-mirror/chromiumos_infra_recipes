# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with FindIt."""

import collections

from google.protobuf import json_format as jsonpb
from google.protobuf import struct_pb2

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

  @property
  def test_bisection_percent(self):
    return self._test_bisection_percent

  @property
  def test_bisection_count(self):
    return self._test_bisection_count

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

  def _create_failures_payload(self, failed_packages, failed_step,
                               needs_bisection):
    """Creates and returns the failures payload used by FindIt.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
      failed_step (str): fully qualified step name, that is the names down to
          nested step concatenated with pipes, of the potentially failing step.
      needs_bisection: (bool): Whether or not bisection is needed for this run.
          A non-critical builder, for example may not need bisection.

    Returns:
      dict: failures payload used by FindIt to identify failures and later
          echo them back during bisection builds.
    """
    failures = []
    for pkg in failed_packages:
      # Strip version off PackageInfo, breaks bisect invoked install packages.
      failures.append({
          'rule': 'emerge',
          'output_targets': [
              jsonpb.MessageToJson(
                  PackageInfo(category=pkg.category,
                              package_name=pkg.package_name))
          ],
          'needs_bisection': needs_bisection,
      })
    return {
        'failures': failures,
        'failed_step': failed_step,
    }

  def set_compile_failures(self, failed_packages, failed_step, needs_bisection):
    """Outputs the failed packages, if any, for FindIt consumption.

    Outputs build failure of the indicated packages for consumption by FindIt
    under the output property "compile_failures". If there are no
    failed packages this method outputs nothing.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
      failed_step (str): fully qualified step name, that is the names down to
          nested step concatenated with pipes, of the potentially failing step.
      needs_bisection: (bool): Whether or not bisection is needed for this run.
          A non-critical builder, for example may not need bisection.
    """
    if not failed_packages:
      return
    payload = self._create_failures_payload(failed_packages, failed_step,
                                            needs_bisection)
    self.m.easy.set_properties_step(compile_failures=payload)

  def set_test_failures(self, hw_results, needs_bisection):
    """Outputs the failed hardware tests, if any, for FindIt consumption.

    Outputs hardware test failures from the results for consumption by FindIt
    under the output property "test_failures". If there are no failed hardware
    tests this method outputs nothing.

    Args:
      hw_results (list[SkylabResult]): list of SkylabResults from running
          hardware tests
      needs_bisection: (bool): Whether or not bisection is needed for this run.
    """
    hw_failed_results = [
        result for result in hw_results
        if self.m.failures.is_critical_hw_test_failure(result)
    ]
    hw_test_failures = []
    for result in hw_failed_results:
      # These are split out into separate units as each test failure must
      # travel with the suite that failed for FindIt (for grouping), and FindIt
      # does not introspect the test_spec value.
      test = result.task.test
      hw_test_cfg = HwTestCfg(hw_test=[test])
      unit = HwTestUnit(common=result.task.unit.common, hw_test_cfg=hw_test_cfg)
      hw_test_failures.append({
          # This must match the step name as known by sherrif-o-matic.
          'failed_step':
              'check test results|hw test results|' + test.common.display_name,
          'test_spec':
              jsonpb.MessageToJson(unit),
          'suite':
              test.suite,
      })
    if hw_test_failures:
      payload = {
          'hw_test_failures': hw_test_failures,
          'needs_bisection': needs_bisection,
      }
      self.m.easy.set_properties_step(test_failures=payload)

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
      child_builders.add(hw_test_unit.common.build_target.name + '-snapshot')
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
    for _, units in hw_test_units.iteritems():
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
