# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Callable, Dict

from google.protobuf import duration_pb2, struct_pb2

from PB.chromiumos.test.api import test_suite as ctr_test_suite
from PB.lab import license as license_pb2
from PB.recipe_modules.chromeos.skylab.examples.schedule_suites import ScheduleSuitesProperties
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/json',
    'recipe_engine/properties',
    'cros_test_plan',
    'git_footers',
    'metadata',
    'skylab',
]


PROPERTIES = ScheduleSuitesProperties


def RunSteps(api, properties: ScheduleSuitesProperties):
  builder_name = 'test-board-release-main'
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test_unit.common.builder_name = builder_name
  hw_test_unit.common.build_target.name = 'test-board'
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.skylab_board = 'specific-model'
  hw_test.common.display_name = 'my_first_little_hwtest'
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test_unit.common.builder_name = builder_name
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'my_second_little_hwtest'
  another_unit_hw_test = UnitHwTest(unit=another_hw_test_unit,
                                    hw_test=another_hw_test)

  non_crit_hw_test_unit = api.cros_test_plan.test_api.non_critical_hw_test_unit(
  )
  non_crit_hw_test_unit.common.builder_name = builder_name
  non_crit_hw_test = non_crit_hw_test_unit.hw_test_cfg.hw_test[0]
  non_crit_hw_test.common.display_name = 'my_third_little_hwtest'
  non_crit_unit_hw_test = UnitHwTest(unit=non_crit_hw_test_unit,
                                     hw_test=non_crit_hw_test)

  hw_test_unit_with_license = api.cros_test_plan.test_api.hw_test_unit
  hw_test_unit_with_license.common.builder_name = builder_name
  hw_test_with_license = hw_test_unit_with_license.hw_test_cfg.hw_test[0]
  hw_test_with_license.licenses.extend([
      license_pb2.LICENSE_TYPE_WINDOWS_10_PRO,
      license_pb2.LICENSE_TYPE_MS_OFFICE_STANDARD,
  ])
  unit_hw_test_with_license = UnitHwTest(unit=hw_test_unit_with_license,
                                         hw_test=hw_test_with_license)

  # HW Test Unit opted-in to running via container
  hw_test_unit_container = api.cros_test_plan.test_api.hw_test_unit
  hw_test_unit_container.common.builder_name = builder_name
  hw_test_container = hw_test_unit_with_license.hw_test_cfg.hw_test[0]
  hw_test_container.run_via_cft = True
  hw_test_container.run_via_trv2 = True
  hw_test_container.total_shards = 5
  hw_test_container.tag_criteria.CopyFrom(
      ctr_test_suite.TestSuite.TestCaseTagCriteria(
          tags=['include_this_tag_1', 'include_this_tag_2'],
          tag_excludes=['exclude_this_tag_1',
                        'exclude_this_tag_2'], test_names=['include_this_test'],
          test_name_excludes=['exlude_this_test']))
  unit_hw_test_container = UnitHwTest(
      unit=hw_test_unit_container,
      hw_test=hw_test_container,
  )

  api.skylab.set_qs_account('a_new_quota_account')
  api.assertions.assertEqual(api.skylab.qs_account, 'a_new_quota_account')
  api.skylab.apply_qs_account_overrides(
      api.buildbucket.build.input.gerrit_changes)

  build_target_critical_allowlist = None
  if properties.pass_build_target_critical_allowlist:
    build_target_critical_allowlist = properties.build_target_critical_allowlist
  tasks = api.skylab.schedule_suites(
      [
          unit_hw_test,
          another_unit_hw_test,
          non_crit_unit_hw_test,
          unit_hw_test_with_license,
          unit_hw_test_container,
      ], timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(target='target'),
      build_target_critical_allowlist=build_target_critical_allowlist,
      require_stable_devices=properties.require_stable_devices)

  api.assertions.assertEqual(len(tasks), 5)
  api.assertions.assertCountEqual(
      [x.test for x in tasks],
      [
          hw_test,
          another_hw_test,
          non_crit_hw_test,
          hw_test_with_license,
          hw_test_container,
      ],
  )


def GenTests(api):
  yield api.test('basic',
                 api.buildbucket.ci_build(builder='release-main-orchestrator'))

  yield api.test('basic-cq', api.cq(run_mode=api.cq.FULL_RUN),
                 api.buildbucket.ci_build(builder='cq-orchestrator'))

  def HardwareAttributesEquals(check, step_odict, step: str, log: str,
                               display_name: str, expected: dict):
    """Assert that a test's HardwareAttributes are equal to a given dict.

    Args:
      step - The step to check the log of.
      log - The name of the log to check.
      display_name - The name of the test to check.
      expected - The expected value of the HardwareAttributes.

    Usage:
      yield (
          TEST
          + api.post_process(HardwareAttributesEquals, 'step-name', 'log-name', 'display-name', {'key': 'value'})
      )
    """
    data = api.json.loads(step_odict[step].logs[log])
    check(data['requests'][0]['scheduleBuild']['properties']['requests']
          [display_name]['params']['hardwareAttributes'] == expected)

  yield api.test(
      'require-stable-devices',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.ci_build(builder='cq-orchestrator'),
      api.properties(ScheduleSuitesProperties(require_stable_devices=True)),
      # The first hwtest sets a specific model and should not set
      # requireStableDevice; the second hwtest doesn't set a specific model, so
      # should set requireStableDevice.
      api.post_check(HardwareAttributesEquals,
                     'schedule skylab tests v2.buildbucket.schedule', 'request',
                     'my_first_little_hwtest', {
                         'model': 'model',
                     }),
      api.post_check(HardwareAttributesEquals,
                     'schedule skylab tests v2.buildbucket.schedule', 'request',
                     'my_second_little_hwtest', {'requireStableDevice': True}),
  )

  yield api.test(
      'build-target-allowlist-disabled',
      api.buildbucket.ci_build(builder='release-main-orchestrator'),
      api.properties(
          ScheduleSuitesProperties(
              pass_build_target_critical_allowlist=False,
              build_target_critical_allowlist=['zork'],
          ),
      ),
      api.post_check(
          post_process.LogContains,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"CRITICAL"'],
      ),
      api.post_check(
          post_process.LogDoesNotContain,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"NON_CRITICAL"'],
      ),
  )

  yield api.test(
      'build-target-allowlist-no-match-non-critical',
      api.buildbucket.ci_build(builder='release-main-orchestrator'),
      api.properties(
          ScheduleSuitesProperties(
              pass_build_target_critical_allowlist=True,
              build_target_critical_allowlist=['zork'],
          ),
      ),
      api.post_check(
          post_process.LogContains,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"NON_CRITICAL"'],
      ),
      api.post_check(
          post_process.LogDoesNotContain,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"CRITICAL"'],
      ),
  )

  yield api.test(
      'build-target-allowlist-match-critical',
      api.buildbucket.ci_build(builder='release-main-orchestrator'),
      api.properties(
          ScheduleSuitesProperties(
              pass_build_target_critical_allowlist=True,
              build_target_critical_allowlist=['test-board'],
          ),
      ),
      api.post_check(
          post_process.LogContains,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"CRITICAL"'],
      ),
      api.post_check(
          post_process.LogDoesNotContain,
          'schedule skylab tests v2.create test requests.configure test-board-release-main (specific-model)',
          'request',
          ['"NON_CRITICAL"'],
      ),
  )

  yield api.test(
      'exclude-sub-invs',
      api.buildbucket.ci_build(builder='release-main-orchestrator'),
      api.properties(
          **{'$chromeos/skylab': SkylabProperties(exclude_sub_invs=True)}),
  )

  build = api.buildbucket.try_build_message(project='chromeos',
                                            bucket='chromeos',
                                            builder='cq-orchestrator',
                                            experiments={'chromeos.a.b': True})
  yield api.test(
      'experiments', api.buildbucket.build(build),
      api.git_footers.simulated_get_footers(['chromeos.c.d', 'chromeos.e.f'],
                                            'schedule skylab tests v2'))

  def verify_qs_account_unmanaged(check: Callable[[bool],
                                                  bool], steps: Dict[str, Step],
                                  qs_account: str) -> bool:
    data = api.json.loads(
        steps['schedule skylab tests v2.buildbucket.schedule'].stdin)
    return check('label-quota-account:{}'.format(qs_account) in data['requests']
                 [0]['scheduleBuild']['properties']['requests']
                 ['my_first_little_hwtest']['params']['decorations']['tags'])

  yield api.test(
      'unmanaged_qs_account',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p0_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.post_check(verify_qs_account_unmanaged, 'p0_cq_unmanaged'),
  )

  props = struct_pb2.Struct()
  props['sheriff_rotations'] = ['chromeos']
  build = api.buildbucket.try_build_message(project='chromeos',
                                            bucket='chromeos',
                                            builder='release-orchestrator',
                                            properties=props)
  yield api.test(
      'sheriff_rotations', api.buildbucket.build(build),
      api.post_check(post_process.LogContains,
                     'schedule skylab tests v2.buildbucket.schedule', 'request',
                     ['sheriff_rotations']))
