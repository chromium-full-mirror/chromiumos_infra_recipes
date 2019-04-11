# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
from urlparse import urlparse

from recipe_engine import recipe_test_api

from google.protobuf.json_format import MessageToDict

from PB.testplans.generate_test_plan import TestUnit
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class TestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def example_test_plan(self, *units):
    test_plan = GenerateTestPlanResponse()
    for unit in units:
      test_plan.test_unit.add().MergeFrom(unit)

    return test_plan

  def example_hw_unit(self, test_suites=['test-suite'],
                      build_target='build_target',
                      artifact_path='path/to/artifact'):
    unit = TestUnit()
    unit.scheduling_requirements.build_target = build_target
    unit.build_payload.artifacts_gs_path = artifact_path

    for test_suite in test_suites:
      unit.hw_test_cfg.hw_test.add().suite = test_suite

    return unit

  def example_vm_unit(self, test_suites=['test-suite'],
                      build_target='build_target',
                      artifact_path='path/to/artifact'):
    unit = TestUnit()
    unit.scheduling_requirements.build_target = build_target
    unit.build_payload.artifacts_gs_path = artifact_path

    for test_suite in test_suites:
      unit.vm_test_cfg.vm_test.add().test_suite = test_suite

    return unit

  def example_tast_vm_unit(self, test_env='', test_suites=['test-suite'],
                           build_target='build_target',
                           artifact_path='path/to/artifact'):
    unit = TestUnit()
    unit.scheduling_requirements.build_target = build_target
    unit.build_payload.artifacts_gs_path = artifact_path

    for test_suite in test_suites:
      unit.tast_vm_test_cfg.tast_vm_test.add().suite_name = test_suite

    return unit

  def fail_schedule(self, name, test_env='hw', test_suite='test-suite'):
    substep = step_name(test_env=test_env, test_suite=test_suite)
    return self.step_data('%s.%s' % (name, substep), retcode=1)

  def simulated_generate_output(self, name, test_plan):
    return self.step_data(name, self.m.json.output(MessageToDict(test_plan)))

  def simulate_test_builds(self, name):
    test_suites = ['suite1', 'suite2']
    test_units = [
      self.example_hw_unit(test_suites=test_suites),
      self.example_vm_unit(test_suites=test_suites),
    ]

    result = self.simulated_generate_output('%s.generate' % name,
                                            self.example_test_plan(*test_units))

    for test_unit in test_units:
      result += self.m.skylab.simulated_create_suites(
          '%s.schedule.build_target.hw' % name, test_unit)

      for idx, test in enumerate(test_unit.vm_test_cfg.vm_test):
        substep_name = '%s.vm.%s' % (
            test_unit.scheduling_requirements.build_target, test.test_suite)
        result += self.step_data(
            '%s.schedule.%s' % (name, substep_name),
            self.m.swarming.trigger(['task - %s' % str(idx)]))

    return result

  def simulated_collect_output(self, name, failure=False):
    # TODO(yshaul): use properties config rather than hardcoding name
    # hostname = 'vm_swarming_server.com'
    hostname = urlparse(self.m.vm_test.swarming_server).hostname
    return self.step_data(
        '%s.%s' % (name, hostname),
        self.m.swarming.collect(
            [self.m.swarming.task_result(1, 'vm-test', failure=failure)]))

  def fail_test_builds(self, name):
    # Bounce on the first infra step of test_build
    return self.step_data('%s.generate' % name, retcode=1)


def step_name(test_env, test_suite):
  """Returns step name for test plan.

  Args:
    * test_env (str): Name of test env.
    * test_suite (str): Name of test suite.

  Returns:
    str: Step name
  """
  return '%s.%s' % (test_env, test_suite)
