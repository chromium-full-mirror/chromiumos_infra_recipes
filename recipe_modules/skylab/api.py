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
  UnitHwTest = structs.UnitHwTest

  def __init__(self, properties, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    # TODO(crbug.com/991703): Once there is a meaninful cipd package tag that
    # corresponds to a CI-blessed version of the skylab tool, track it
    # instead of the "latest" tag.
    self._version = str(properties.skylab_version) or 'latest'
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'

  def set_qs_account(self, qs_account):
    """Override the quota scheduler account at runtime."""
    self._qs_account = qs_account

  def schedule_suites(self, unit_hw_tests, timeout, name=None):
    """Schedule HW test suites by invoking the cros_test_platform recipe.

    Args:
      tests (list[UnitHwTest]): Hardware test suites to execute
      timeout (Duration): Timeout in timestamp_pb2.Duration.
      name (str): The step name. Defaults to 'schedule skylab tests v2'

    Returns:
      list[SkylabTask]: with buildbucket_id of the recipe launched.
    """
    name = name or 'schedule skylab tests v2'
    with self.m.step.nest(name) as presentation:
      # str -> (Request dict)
      reqs = {}

      for uht in unit_hw_tests:
        req = Request()
        req.params.hardware_attributes.model = ''
        req.params.time.maximum_duration.seconds = timeout.seconds
        image_path = uht.unit.common.build_payload.artifacts_gs_path
        gs_url = ('gs://' + uht.unit.common.build_payload.artifacts_gs_bucket +
                  '/' + uht.unit.common.build_payload.artifacts_gs_path)
        req.params.metadata.test_metadata_url = gs_url
        req.params.metadata.debug_symbols_archive_url = gs_url
        self._set_pool(req.params.scheduling, uht.hw_test.pool)
        sw_dep = req.params.software_dependencies.add()
        sw_dep.chromeos_build = image_path
        req.params.scheduling.qs_account = self._qs_account
        req.params.software_attributes.build_target.name = uht.hw_test.skylab_board
        suite_to_create = req.test_plan.suite.add()
        suite_to_create.name = uht.hw_test.suite

        tags = self._get_ctp_tags(uht.hw_test, uht.unit, image_path)
        request_tags = [
            '{}:{}'.format(key, value) for key, value in tags.items()
        ]
        req.params.decorations.tags.extend(request_tags)
        self._enable_test_retries(req)
        reqs[_request_tag(uht.hw_test)] = json_format.MessageToDict(req)

      bb_request = self.m.buildbucket.schedule_request(
          'cros_test_platform', bucket='testplatform', properties={
              'requests': reqs,
          }, gerrit_changes=[], swarming_parent_run_id=self.m.swarming.task_id)
      build = self.m.buildbucket.schedule([bb_request])[0]

      build_url = self.m.buildbucket.build_url(build_id=build.id)
      presentation.links['suite link'] = build_url

      tasks = []
      for uht in unit_hw_tests:
        tasks.append(
            self.SkylabTask(id=build.id, url=build_url, test=uht.hw_test,
                            unit=uht.unit))
      return tasks

  def _set_pool(self, scheduling, pool_name):
    if pool_name == 'DUT_POOL_QUOTA':
      scheduling.managed_pool = Request.Params.Scheduling.MANAGED_POOL_QUOTA
    else:
      scheduling.unmanaged_pool = pool_name
    return

  def create_recipe(self, test, unit, timeout, name=None):
    """Schedule a HW test suite by invoking the cros_test_platform recipe.

    Args:
      test (HwTest): A hardware test config.
      unit (HwTestUnit): The unit the test was defined in.
      timeout (Duration): Timeout in timestamp_pb2.Duration.
      name (str): The step name. Defaults to 'schedule <test title>'

    Returns:
      SkylabTask: with buildbucket_id of the recipe launched.
    """
    name = name or 'schedule %s' % test.common.display_name
    with self.m.step.nest(name) as presentation:
      req = Request()
      req.params.hardware_attributes.model = ""
      req.params.time.maximum_duration.seconds = timeout.seconds
      image_path = unit.common.build_payload.artifacts_gs_path
      req.params.metadata.test_metadata_url = (
          'gs://' + unit.common.build_payload.artifacts_gs_bucket + '/' +
          unit.common.build_payload.artifacts_gs_path)
      self._set_pool(req.params.scheduling, test.pool)
      sw_dep = req.params.software_dependencies.add()
      sw_dep.chromeos_build = image_path
      req.params.scheduling.qs_account = self._qs_account
      req.params.software_attributes.build_target.name = test.skylab_board
      suite_to_create = req.test_plan.suite.add()
      suite_to_create.name = test.suite

      tags = self._get_ctp_tags(test, unit, image_path)
      request_tags = ['{}:{}'.format(key, value) for key, value in tags.items()]
      bb_tags = [
          common_pb2.StringPair(key=key, value=value)
          for key, value in tags.items()
      ]
      req.params.decorations.tags.extend(request_tags)
      self._enable_test_retries(req)

      request_dict = json_format.MessageToDict(req)
      bb_request = self.m.buildbucket.schedule_request(
          'cros_test_platform', bucket='testplatform', properties={
              'request': request_dict,
          }, tags=bb_tags, gerrit_changes=[],
          swarming_parent_run_id=self.m.swarming.task_id)
      build = self.m.buildbucket.schedule([bb_request])[0]

      build_url = self.m.buildbucket.build_url(build_id=build.id)
      presentation.links['suite link'] = build_url
      return self.SkylabTask(id=build.id, url=build_url, test=test, unit=unit)

  def _get_ctp_tags(self, test, unit, image_path):
    return {
        'label-pool': test.pool,
        'build': image_path,
        'label-board': test.skylab_board,
        'suite': test.suite,
    }

  def _enable_test_retries(self, req):
    """Enable test retries within suites.

    The values here are in-line with what LCQ currently does.

    Args:
      params: A request.Request object.
    """
    req.params.retry.max = 5
    req.params.retry.allow = True

  def wait_on_suites(self, tasks, timeout):
    """Wait for the single Skylab multi-request to finish and return the result

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.
      timeout (Duration): Timeout in timestamp_pb2.Duration.

    Returns:
      list[SkylabResult]: The results for suites from provided tasks.
    """
    if not tasks:
      return []
    with self.m.step.nest('collect skylab tasks v2') as presentation:

      # All the tasks contain the same cros_test_platform build ID.
      task_id = tasks[0].id
      # Give 30 minutes grace period for recipes to time out.
      timeout_seconds = int(timeout.seconds + 30 * 60)
      try:
        hw_tests = self.m.buildbucket.collect_builds(
            [task_id], timeout=timeout_seconds)[task_id]
      except recipe_api.StepFailure as ex:  #pragma: no cover
        # Mark the step as an INFRA_FAILURE and get the output
        # properties of underlying recipes.
        presentation.status = 'EXCEPTION'
        hw_tests = self.m.buildbucket.get_multi([task_id])[task_id]

      results = []
      responses = self._get_multi_response(hw_tests)
      for t in tasks:
        result = responses.get(
            _request_tag(t.test), self._default_failed_response())
        results.append(self._translate_result(result, t))

      presentation.logs['return value'] = [str(r) for r in results]
      return results

  def _get_multi_response(self, build):
    # ExecuteResponse is stored as a Struct in output.properties.
    # This helper handles the re-casting and error catching.
    responses = {}
    try:
      responses_prop = build.output.properties['responses']
    except (KeyError, ValueError):
      return responses

    for tag, response_struct in responses_prop.fields.iteritems():
      response = ExecuteResponse()
      try:
        response_json = json_format.MessageToJson(response_struct.struct_value)
        json_format.Parse(response_json, response, ignore_unknown_fields=True)
      except (ValueError, json_format.ParseError) as e:  #pragma: no cover
        response = self._default_failed_response()
      finally:
        responses[tag] = response
    return responses

  def wait_on_recipes(self, tasks, timeout):
    """Wait for all Skylab suites to finish and return the results.

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.
      timeout (Duration): Timeout in timestamp_pb2.Duration.

    Returns:
      list[SkylabResult]: The results for each suite.
    """
    tasks_by_id = {task.id: task for task in tasks}

    with self.m.step.nest('collect skylab tasks') as presentation:
      task_ids = [task.id for task in tasks]
      # Give 30 minutes grace period for recipes to time out.
      timeout_seconds = int(timeout.seconds + 30 * 60)
      try:
        all_hw_tests = self.m.buildbucket.collect_builds(
            task_ids, timeout=timeout_seconds)
      except recipe_api.StepFailure as ex:  #pragma: no cover
        # Mark the step as an INFRA_FAILURE and get the output
        # properties of underlying recipes.
        presentation.status = 'EXCEPTION'
        all_hw_tests = self.m.buildbucket.get_multi(task_ids)

      results = []
      for test_id, test in all_hw_tests.items():
        test_response = self._get_execute_response(test)
        results.append(
            self._translate_result(test_response, tasks_by_id[test_id]))

      presentation.logs['return value'] = [str(x) for x in results]
      return results

  def _get_execute_response(self, build):
    # ExecuteResponse is stored as a Struct in output.properties.
    # This helper handles the re-casting and error catching.
    try:
      response_struct = build.output.properties['response']
      response_json = json_format.MessageToJson(response_struct)
      response = ExecuteResponse()
      json_format.Parse(response_json, response, ignore_unknown_fields=True)
    except (ValueError, json_format.ParseError) as e:  #pragma: no cover
      return self._default_failed_response()

    return response

  def _default_failed_response(self):
    response = ExecuteResponse()
    response.state.verdict = TaskState.VERDICT_FAILED
    response.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
    return response

  def _translate_result(self, result, task):
    """Translates result to a Skylab result."""
    if result.state.verdict == TaskState.VERDICT_PASSED:
      status = common_pb2.SUCCESS
    elif result.state.life_cycle in (TaskState.LIFE_CYCLE_CANCELLED,
                                     TaskState.LIFE_CYCLE_PENDING,
                                     TaskState.LIFE_CYCLE_ABORTED,
                                     TaskState.LIFE_CYCLE_REJECTED):
      status = common_pb2.INFRA_FAILURE
    else:
      status = common_pb2.FAILURE
    return self.SkylabResult(task=task, status=status,
                             child_results=result.task_results)

def _request_tag(hw_test):
  return hw_test.common.display_name
