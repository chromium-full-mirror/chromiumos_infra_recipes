# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import json

from recipe_engine import recipe_api

# GS BUCKET in which to archive build artifacts.
ARCHIVE_BUCKET = 'chromeos-image-archive'

SWARMING_POOL = 'VMTest'
SWARMING_MED_PRIORITY = 100

# Name of swarming job. Appends test suite name.
SWARMING_TEST_NAME = 'vm-test-%s'


class VMTestApi(recipe_api.RecipeApi):
  """A module for vm test execution steps"""

  def run_vm_tests(self, name, test_unit):
    """Run vm test on swarming bot.

    Args:
      * name (str): Step name.
      * test_unit (TestUnit): Test unit.

    Returns:
      list[swarming.TaskRequestMetadata]
    """
    result = []
    with self.m.step.nest(name):
      for test in test_unit.vm_test_cfg.vm_test:
        result.append(
            self._run(
                test.test_suite,
                build_target=test_unit.scheduling_requirements.build_target,
                test_suite=test.test_suite,
                gs_path=test_unit.build_payload.artifact_path, test_type='vm'))

    return result

  def run_tast_vm_tests(self, name, test_unit):
    """Run tast test on swarming bot.

    Args:
      * name (str): Step name.
      * test_unit (TestUnit): Test unit.

    Returns:
      list[swarming.TaskRequestMetadata]
    """
    result = []
    with self.m.step.nest(name):
      for test in test_unit.tast_vm_test_cfg.tast_vm_test:
        result.append(
            self._run(
                test.suite_name,
                build_target=test_unit.scheduling_requirements.build_target,
                test_suite=test.suite_name,
                gs_path=test_unit.build_payload.artifact_path, test_exprs=[
                    expr.test_expr for expr in test.tast_test_expr
                ], test_type='tast_vm'))

    return result

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
        'version:latest', 'recipes')

    ensure_file.add_package('infra/depot_tools/depot_tools', 'version:latest',
                            'depot_tools')

    request = (
        self.m.swarming.task_request().with_name(
            SWARMING_TEST_NAME %
            str(test_suite)).with_priority(SWARMING_MED_PRIORITY))

    cmd = [
        'recipes/recipes.py',
        'run',
        '--workdir',
        'recipes/workdir',
        '--properties',
        json.dumps(self._get_properties(test_suite=test_suite, **kwargs)),
    ]

    # Configure the first slice.
    request = (
        request.with_slice(
            0, request[0].with_command(cmd).with_dimensions(pool=SWARMING_POOL)
            .with_cipd_ensure_file(ensure_file).with_env_prefixes(
                PATH=["depot_tools"])))

    metadata = self.m.swarming.trigger(name, requests=[request])
    return metadata[0]

  def _get_properties(self, **kwargs):
    ret = {
        'gs_bucket': ARCHIVE_BUCKET,
        '$recipe_engine/path': {
            'cache_dir': '/b/bot/w/ir/cache'
        }
    }
    ret.update(**kwargs)
    return ret
