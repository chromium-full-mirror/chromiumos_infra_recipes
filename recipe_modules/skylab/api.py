# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from collections import namedtuple
from google.protobuf import json_format

from recipe_engine import recipe_api

import structs

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.skylab_tool.result import WaitTasksResult
from PB.test_platform.request import Request
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState


class SkylabApi(recipe_api.RecipeApi):
  """Module for issuing commands to Skylab"""

  SkylabTask = structs.SkylabTask
  SkylabResult = structs.SkylabResult

  def __init__(self, properties, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    self._server = str(
        properties.skylab_server) or 'https://chromeos-swarming.appspot.com'
    # TODO(crbug.com/991703): Once there is a meaninful cipd package tag that
    # corresponds to a CI-blessed version of the skylab tool, track it
    # instead of the "latest" tag.
    self._version = str(properties.skylab_version) or 'latest'
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'
    self._skylab_timeout_mins = properties.skylab_timeout_mins or 7 * 60
    self._skylab_priority = properties.skylab_priority or 140

  def initialize(self):
    self._client = None

  def create_suite(self, test, unit, name=None, dev=False):
    """Schedule a HW test suite.

    Args:
      test (HwTest): A hardware test config.
      unit (HwTestUnit): The unit the test was defined in.
      name (str): The step name. Defaults to 'schedule <test title>'
      dev (boolean): Whether to use Skylab dev instance.

    Returns:
      SkylabTask: The swarming task ID.
    """
    self._ensure_skylab()
    name = name or 'schedule %s' % test.common.display_name
    with self.m.step.nest(name) as step:
      cmd = [
          self._client,
          'create-suite',
          '-json',
          '-pool',
          'DUT_POOL_QUOTA',
          '-image',
          unit.common.build_payload.artifacts_gs_path,
          '-board',
          test.skylab_board,
          '-timeout-mins',
          self._skylab_timeout_mins,  # 7 hours to account for skylab capacity under strain.
          '-qs-account',
          self._qs_account,
          '-task-name',
          test.common.display_name,
      ]
      if dev:
        cmd.append('-dev')
      cmd += test.suite,
      task_json = self.m.easy.stdout_json_step(
          'skylab create-suite', cmd, infra_step=True,
          test_stdout=self.test_api.create_suite_json_output(test.suite))
      task_id = task_json['task_id']
      task_url = task_json['task_url']
      step.presentation.links['swarming task'] = task_url
      return self.SkylabTask(id=task_id, url=task_url, test=test, unit=unit)

  def create_recipe(self, test, unit, name=None):
    """Schedule a HW test suite by invoking the cros_test_platform recipe.

    Args:
      test (HwTest): A hardware test config.
      unit (HwTestUnit): The unit the test was defined in.
      name (str): The step name. Defaults to 'schedule <test title>'

    Returns:
      SkylabTask: with buildbucket_id of the recipe launched.
    """
    name = name or 'schedule %s' % test.common.display_name
    with self.m.step.nest(name) as step:
      req = Request()
      req.params.hardware_attributes.model = ""
      req.params.time.maximum_duration.seconds = self._skylab_timeout_mins * 60
      image_path = unit.common.build_payload.artifacts_gs_path
      req.params.metadata.test_metadata_url = (
          'gs://' + unit.common.build_payload.artifacts_gs_bucket + '/' +
          unit.common.build_payload.artifacts_gs_path)
      req.params.scheduling.priority = self._skylab_priority
      sw_dep = req.params.software_dependencies.add()
      sw_dep.chromeos_build = image_path
      req.params.scheduling.quota_account = self._qs_account
      req.params.software_attributes.build_target.name = test.skylab_board
      suite_to_create = req.test_plan.suite.add()
      suite_to_create.name = test.suite

      tags = self._get_ctp_tags(
          test, unit, self._skylab_priority, image_path)
      request_tags = ['{}:{}'.format(key, value)
                      for key, value in tags.items()]
      bb_tags = [common_pb2.StringPair(key=key, value=value)
                 for key, value in tags.items()]
      req.params.decorations.tags.extend(request_tags)

      request_dict = json_format.MessageToDict(req)
      bb_request = self.m.buildbucket.schedule_request(
          'cros_test_platform', bucket='testplatform', properties={
              'request': request_dict,
          }, tags=bb_tags)
      build = self.m.buildbucket.schedule([bb_request])[0]

      build_url = self.m.buildbucket.build_url(build_id=build.id)
      step.presentation.links['suite link'] = build_url
      return self.SkylabTask(id=build.id, url=build_url, test=test, unit=unit)

  def _get_ctp_tags(self, test, unit, priority, image_path):
    return {
        'label-pool': 'DUT_POOL_QUOTA',
        'priority': str(priority),
        'build': image_path,
        'label-board': test.skylab_board,
        'suite': test.suite,
    }

  def wait_tasks(self, tasks, dev=False):
    """Wait for all Skylab suites to finish and return the results.

    Uses skylab wait-tasks internally.

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.
      dev (boolean): Whether to use Skylab dev instance.

    Returns:
      list[SkylabResult]: The results for each suite.
    """
    self._ensure_skylab()
    tasks_by_id = {task.id: task for task in tasks}

    with self.m.step.nest('collect skylab tasks') as step:
      task_ids = [task.id for task in tasks]
      # TODO(crbug.com/989623) once wait-tasks supports partial results
      # drop the extra 10 min wait.
      cmd = [
          self._client, 'wait-tasks', '-timeout-mins',
          self._skylab_timeout_mins + 10
      ]
      if dev:
        cmd.append('-dev')
      cmd += task_ids
      output_json = self.m.easy.stdout_json_step(
          'skylab wait-tasks', cmd, infra_step=True, ignore_exceptions=True,
          test_stdout=self.test_api.wait_tasks_json_output())

      # Convert parsed-json python dictionary into proto.
      wait_results = WaitTasksResult()
      json_format.Parse(json.dumps(output_json), wait_results)

      results = []
      for wait_result in wait_results.results:
        task_result = wait_result.result
        task_id = int(task_result.task_request_id)
        task_name = tasks_by_id[task_id].test.common.display_name
        task_url = task_result.task_run_url
        step.presentation.links[task_name] = task_url
        results.append(
            self.SkylabResult(task=tasks_by_id[task_id],
                              success=task_result.success,
                              child_results=wait_result.child_results))

      step.presentation.logs['return value'] = [str(x) for x in results]
      return results

  def wait_on_recipes(self, tasks):
    """Wait for all Skylab suites to finish and return the results.

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.

    Returns:
      list[SkylabResult]: The results for each suite.
    """
    tasks_by_id = {task.id: task for task in tasks}

    with self.m.step.nest('collect skylab tasks') as step:
      task_ids = [task.id for task in tasks]
      all_hw_tests = self.m.buildbucket.collect_builds(
          task_ids, timeout=self._skylab_timeout_mins * 60)

      results = []
      for test_id, test in all_hw_tests.items():
        test_response = self._get_execute_response(test)
        success = test_response.state.verdict == TaskState.VERDICT_PASSED
        results.append(
            self.SkylabResult(task=tasks_by_id[test_id], success=success,
                              child_results=test_response.task_results))

      step.presentation.logs['return value'] = [str(x) for x in results]
      return results

  def _get_execute_response(self, build):
    # ExecuteResponse is stored as a Struct in output.properties.
    # This helper handles the re-casting and error catching.
    try:
      response_struct = build.output.properties['response']
      response_json = json_format.MessageToJson(response_struct)
      response = ExecuteResponse()
      json_format.Parse(response_json, response)
    except (ValueError, json_format.ParseError) as e:  #pragma: no cover
      return self._default_failed_response()

    return response

  def _default_failed_response(self):
    response = ExecuteResponse()
    response.state.verdict = TaskState.VERDICT_FAILED
    response.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
    return response

  def _ensure_skylab(self):
    """Ensure the Skylab CLI is installed."""
    if self._client:
      return  # pragma: nocover

    with self.m.step.nest('ensure skylab'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab/${platform}', self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._client = cipd_dir.join('skylab')
