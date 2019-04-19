# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import json

from recipe_engine import recipe_api

from RECIPE_MODULES.chromeos.test_plan.api import ScheduleResult

# GS BUCKET in which to archive build artifacts.
ARCHIVE_BUCKET = 'chromeos-image-archive'

SWARMING_MED_PRIORITY = 100
SWARMING_TEST_NAME = 'vm-test-%s'

VM_TEST_RECIPE = 'test_execution/execute_vm_suite'


class VMTestApi(recipe_api.RecipeApi):
  """A module for vm test execution steps"""

  def __init__(self, vm_test_properties, *args, **kwargs):
    super(VMTestApi, self).__init__(*args, **kwargs)
    self._swarming_server = vm_test_properties.get('swarming_server', None)
    self._swarming_pool = vm_test_properties.get('swarming_pool', None)

  def initialize(self):
    if self._test_data.enabled:
      self._swarming_server = self.test_api.swarming_server
      self._swarming_pool = self.test_api.swarming_pool

  @property
  def swarming_server(self):
    return self._swarming_server

  @property
  def swarming_pool(self):
    return self._swarming_pool

  def run_vm_tests(self, name, build_target, test_unit):
    """Run vm test on swarming bot.

    Args:
      * name (str): Step name.
      * build_target (str): Build target.
      * test_unit (TestUnit): Test unit.

    Returns:
      swarming.TaskRequestMetadata
    """
    tasks = []
    with self.m.step.nest(name):
      for test in test_unit.vm_test_cfg.vm_test:
        tasks.append(
            self._run(
                test.test_suite,
                build_target=build_target,
                test_suite=test.test_suite,
                gs_path=test_unit.build_payload.artifacts_gs_path,
                test_type='vm'))

    return ScheduleResult(swarming_server=self.swarming_server, tasks=tasks)

  def run_tast_vm_tests(self, name, build_target, test_unit):
    """Run tast test on swarming bot.

    Args:
      * name (str): Step name.
      * build_target (str): Build target.
      * test_unit (TestUnit): Test unit.

    Returns:
      swarming.TaskRequestMetadata
    """
    tasks = []
    with self.m.step.nest(name):
      for test in test_unit.tast_vm_test_cfg.tast_vm_test:
        tasks.append(
            self._run(
                '%s_%s' % (build_target, test.suite_name),
                build_target=build_target,
                test_suite=test.suite_name,
                gs_path=test_unit.build_payload.artifacts_gs_path, test_exprs=[
                    expr.test_expr for expr in test.tast_test_expr
                ], test_type='tast_vm'))

    return ScheduleResult(swarming_server=self.swarming_server, tasks=tasks)

  def _run(self, name, test_suite, **kwargs):
    """Trigger test on swarming bot.

    Args:
      * name (str): Step name.
      * test_suite (str): name of test suite.
      * kwargs: Task properties.

    Returns:
      swarming.TaskRequestMetadata
    """
    ensure_file = self.m.cipd.EnsureFile()
    ensure_file.add_package(
        'infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
        'refs/heads/master', 'recipes')

    ensure_file.add_package('infra/tools/luci/vpython/${platform}',
                            'latest',
                            'vpython')

    request = (
        self.m.swarming.task_request().with_name(
            SWARMING_TEST_NAME %
            str(test_suite)).with_priority(SWARMING_MED_PRIORITY))

    cmd = [
        'recipes/recipes',
        'run',
        '--workdir',
        'recipes/workdir',
        '--properties',
        json.dumps(self._get_properties(test_suite=test_suite, **kwargs)),
        VM_TEST_RECIPE,
    ]

    # Configure the first slice.
    request = (
        request.with_slice(
            0, request[0]
            .with_command(cmd)
            .with_execution_timeout_secs(3600 * 2)
            .with_dimensions(pool=self.swarming_pool)
            .with_cipd_ensure_file(ensure_file)
            .with_env_prefixes(PATH=["vpython"])))

    with self.m.swarming.with_server(self.swarming_server):
      metadata = self.m.swarming.trigger(name, requests=[request])

    return metadata[0]

  def _get_properties(self, **kwargs):
    ret = {
        'recipe': VM_TEST_RECIPE,
        'gs_bucket': ARCHIVE_BUCKET,
        '$recipe_engine/path': {
            'cache_dir': '/b/bot/w/ir/cache'
        }
    }
    ret.update(**kwargs)
    return ret
