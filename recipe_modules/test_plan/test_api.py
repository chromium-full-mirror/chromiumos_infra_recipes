# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api
from .api import step_name


class TestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def example_test_plan(self, *units):
    return {'test_unit': units}

  def example_hw_unit(self, test_env='hw', test_suite='test-suite',
                      build_target='build_target', image_name='image.bin',
                      artifact_path='path/to/artifact'):

    return {
        'test_env': test_env,
        'test_suite': test_suite,
        'scheduling_requirements': {
            'build_target': build_target,
        },
        'build_payload': {
            'artifact_path': artifact_path,
            'image': [{
                'image_name': image_name
            }]
        }
    }

  def example_vm_plan(self, test_env='', test_suite='test-suite',
                      build_target='build_target', image_name='image.bin',
                      artifact_path='path/to/artifact'):
    return {
        'test_env': test_env,
        'test_suite': test_suite,
        'artifact_path': artifact_path,
        'scheduling_requirements': {
            'build_target': build_target
        },
        'build_payload': {
            'image': [{
                'image_name': image_name
            }]
        }
    }

  def fail_schedule(self, name, test_env='hw', test_suite='test-suite'):
    substep = step_name({
        'test_env': test_env,
        'test_suite': test_suite,
    })
    return self.step_data('%s.%s' % (name, substep), retcode=1)

  def simulated_generate_output(self, name, test_plan):
    return self.step_data(name, stdout=self.m.json.output(test_plan))

  def simulate_test_builds(self, name):
    test_suites = ['suite1', 'suite2']

    # TODO(yshaul) Use HW plans as well, when skylab starts returning
    # the correct data. crbug/935244
    test_units = [
        self.example_vm_plan(test_env='vm', test_suite=test_suite)
        for test_suite in test_suites
    ]

    result = self.simulated_generate_output('%s.generate' % name,
                                            self.example_test_plan(*test_units))

    for idx, test_unit in enumerate(test_units):
      substep_name = step_name(test_unit)
      result += self.step_data(
          '%s.schedule.%s' % (name, substep_name),
          self.m.swarming.trigger(['task - %s' % str(idx)]))

    return result

  def simulated_collect_output(self, name, failure=False):
    return self.step_data(
        '%s.collect tasks' % name,
        self.m.swarming.collect(
            [self.m.swarming.task_result(1, 'vm-test', failure=failure)]))

  def fail_test_builds(self, name):
    # Bounce on the first infra step of test_build
    return self.step_data('%s.generate' % name, retcode=1)
