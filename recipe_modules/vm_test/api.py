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

  # TODO(yshaul): Update artifact_path when field is implemented.
  #               crbug/935152
  def run_vm_test(self, name, test_plan):
    """Run vm test on swarming bot.

    Args:
      * name (str): Step name.
      * test_plan (TestPlan): Test plan.

    Returns:
      swarming.TaskRequestMetadata
    """
    return self._run(
        name, build_target=test_plan['scheduling_requirements']['build_target'],
        test_suite=test_plan['test_suite'], gs_path=test_plan['artifact_path'],
        test_type='vm')

  def run_tast_test(self, name, test_plan):
    """Run tast test on swarming bot.

    Args:
      * name (str): Step name.
      * test_plan (TestPlan): Test plan.

    Returns:
      swarming.TaskRequestMetadata
    """
    return self._run(
        name,
        build_target=test_plan['scheduling_requirements']['build_target'],
        test_suite=test_plan['test_suite'],
        gs_path=test_plan['artifact_path'],
        # TODO(yshaul): add test_plan['test_exprs'] when available
        test_exprs=[],
        test_type='tast_vm')

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
            test_suite).with_priority(SWARMING_MED_PRIORITY))

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
