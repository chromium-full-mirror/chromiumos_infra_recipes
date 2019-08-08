# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with FindIt."""

from google.protobuf import json_format as jsonpb

from PB.chromiumos.common import PackageInfo
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.target_test_requirements_config import HwTestCfg

from recipe_engine import recipe_api

class CrosBisectApi(recipe_api.RecipeApi):
  """A module for interacting with FindIt."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosBisectApi, self).__init__(*args, **kwargs)
    self._compile = properties.compile
    self._test = properties.test

  def _set_bisect_builder(self, builder):
    self.m.easy.set_property_step('BISECT_BUILDER', builder)

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

  def _create_failures_payload(self, failed_packages):
    """Creates and returns the failures payload used by FindIt.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
    Returns:
      dict: failures payload used by FindIt to identify failures and later
          echo them back during bisection builds.
    """
    failures = []
    for pkg in failed_packages:
      failures.append({
          'rule': 'emerge',
          'output_targets': [jsonpb.MessageToJson(pkg)]
      })
    # TODO: share the constant 'install packages|installation results'
    # with build_target.py?
    return {
        'failures': failures,
        'failed_step': 'install packages|installation results',
    }

  def set_compile_failures(self, failed_packages):
    """Outputs the failed packages, if any, for FindIt consumption.

    Outputs build failure of the indicated packages for consumption by FindIt
    under the output property "compile_failures". If there are no
    failed packages this method outputs nothing.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
    """
    if not failed_packages:
      return
    payload = self._create_failures_payload(failed_packages)
    self.m.easy.set_property_step('compile_failures', payload)

  def set_test_failures(self, hw_results):
    """Outputs the failed hardware tests, if any, for FindIt consumption.

    Outputs hardware test failures from the results for consumption by FindIt
    under the output property "test_failures". If there are no failed hardware
    tests this method outputs nothing.

    Args:
      hw_results (list[SkylabResult]): list of SkylabResults from running
          hardware tests
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
          'failed_step': 'check test results|hw test results|'
          + test.common.display_name,
          'test_spec': jsonpb.MessageToJson(unit),
          'suite': test.suite,
      })
    if hw_test_failures:
      payload = {
        'hw_test_failures': hw_test_failures
      }
      self.m.easy.set_property_step('test_failures', payload)

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
      list[str]: sorted list of child builders to run
    """
    child_builders = set()
    for failure in self._test.hw_test_failures:
      hw_test_unit = jsonpb.Parse(failure.test_spec, HwTestUnit())
      child_builders.add(hw_test_unit.common.build_target.name + '-snapshot')
    return sorted(child_builders)
