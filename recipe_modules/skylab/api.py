# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64

from google.protobuf import json_format

from recipe_engine import recipe_api

from . import structs

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.lab import license as license_pb2
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.test_platform.request import Request
from PB.test_platform.steps.execution import ExecuteResponse, ExecuteResponses
from PB.test_platform.taskstate import TaskState


class SkylabApi(recipe_api.RecipeApi):
  """Module for issuing commands to Skylab"""

  SkylabTask = structs.SkylabTask
  SkylabResult = structs.SkylabResult
  UnitHwTest = structs.UnitHwTest

  def __init__(self, properties, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'
    self._ctp_builder = str(properties.ctp_builder) or 'cros_test_platform'
    self._enable_retries = properties.enable_retries
    self._add_resultdb_settings = properties.add_resultdb_settings

  def initialize(self):
    # TODO(b/196956525): Remove once uploading to rdb is stable.
    self._add_resultdb_settings |= ('chromeos.skylab.add_resultdb_settings' in
                                    self.m.cros_infra_config.experiments)

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  def set_qs_account(self, qs_account):
    """Override the quota scheduler account at runtime."""
    self._qs_account = qs_account

  def schedule_ctp_requests(self, tagged_requests, swarming_parent_run_id=None,
                            bb_tags=None, **kwargs):
    """Schedule a cros_test_platform build.

    Args:
      tagged_requests (dict): Dictionary of string to test_platform.Request
        objects.
      swarming_parent_run_id (str): Swarming run id to with which to associate
        the child build request.
      bb_tags (dict or list[StringPair]): If of the type list[StringPair], will
        be used directly as a bb_tag list. If a dict, used to map keys to values.
        If the value is a list, multiple tags for the same key will be created.
      kwargs: List of extra named parameters to pass to
        buildbucket.schedule_request.
    Returns:
      The scheduled buildbucket build.
    """
    bb_tags = self.m.cros_tags.tags(
        **bb_tags) if isinstance(bb_tags, dict) else bb_tags
    # TODO(b/200175693): This logic also exists in build plan. Consider moving
    # to a common source.
    exps = self.m.cros_infra_config.experiments_for_child_build
    footer_exps = self.m.git_footers.get_footer_values(
        self.m.src_state.gerrit_changes, self.CROS_EXPERIMENTS_FOOTER,
        step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
    exps.update({x: True for x in footer_exps})

    bb_request = self.m.buildbucket.schedule_request(
        self._ctp_builder,
        bucket='testplatform',
        properties={
            'requests': tagged_requests,
        },
        tags=bb_tags if bb_tags else [],
        experiments=exps,
        # TODO(b/186217519,b/186218358): Pass in gerrit_changes and
        # gitiles_commit from src_state to create CTP tile. Relying on buildset
        # tags here is incorrect according to buildbucket V2.
        gerrit_changes=self.m.src_state.gerrit_changes,
        swarming_parent_run_id=swarming_parent_run_id,
        # Disable inheriting the version from the parent builder.
        exe_cipd_version='',
        **kwargs)
    return self.m.buildbucket.schedule([bb_request])[0]

  def schedule_suites(self, unit_hw_tests, timeout, name=None,
                      async_suite_run=False):
    """Schedule HW test suites by invoking the cros_test_platform recipe.

    Args:
    * tests (list[UnitHwTest]): Hardware test suites to execute
    * timeout (Duration): Timeout in timestamp_pb2.Duration.
    * name (str): The step name. Defaults to 'schedule skylab tests v2'
    * async_suite_run (bool): If set, indicates that caller does not intend to wait for
      the scheduled suites to complete, and the child build can outlive the parent build.

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
        image_bucket = uht.unit.common.build_payload.artifacts_gs_bucket
        gs_url = ('gs://' + image_bucket + '/' + image_path)
        req.params.metadata.test_metadata_url = gs_url
        req.params.metadata.debug_symbols_archive_url = gs_url
        self._set_pool(req.params.scheduling, uht.hw_test.pool)
        sw_dep = req.params.software_dependencies.add()
        sw_dep.chromeos_build = image_path
        sw_dep_gsc_bucket = req.params.software_dependencies.add()
        sw_dep_gsc_bucket.chromeos_build_gcs_bucket = image_bucket
        req.params.scheduling.qs_account = self._qs_account
        req.params.software_attributes.build_target.name = uht.hw_test.skylab_board
        suite_to_create = req.test_plan.suite.add()
        suite_to_create.name = uht.hw_test.suite
        self._set_license_labels(req, uht.hw_test.licenses)

        tags = self._get_ctp_tags(uht.hw_test, image_path)
        request_tags = [
            '{}:{}'.format(key, value) for key, value in tags.items()
        ]
        req.params.decorations.tags.extend(request_tags)
        # TODO(b/196956525): Remove check for experiment once uploading to rdb
        # is stable.
        if (self._add_resultdb_settings and
            uht.hw_test.hw_test_suite_type == HwTestCfg.TAST):
          resultdb_settings = self.m.json.dumps({
              'result_format': 'tast',
          })
          req.params.decorations.test_args[
              'resultdb_settings'] = base64.b64encode(resultdb_settings)
        if self._enable_retries:
          self._enable_test_retries(req)
        reqs[_request_tag(uht.hw_test)] = json_format.MessageToDict(req)

      bb_tags = self.m.cros_tags.make_schedule_tags(
          self.m.cros_infra_config.gitiles_commit, inherit_buildsets=True)
      swarming_parent_run_id = None if async_suite_run else self.m.swarming.task_id
      build = self.schedule_ctp_requests(
          tagged_requests=reqs, swarming_parent_run_id=swarming_parent_run_id,
          bb_tags=bb_tags, inherit_buildsets=False)

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

  def _set_license_labels(self, request, licenses):
    """Set params on request for licenses."""
    for lic in licenses:
      dimension = "label-license:" + license_pb2.LicenseType.Name(lic)
      request.params.freeform_attributes.swarming_dimensions.append(dimension)

  def _get_ctp_tags(self, test, image_path):
    result = {
        'label-pool': test.pool,
        'build': image_path,
        'label-board': test.skylab_board,
        'suite': test.suite,
    }
    if test.skylab_model:
      result['label-model'] = test.skylab_model
    return result

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
      except recipe_api.StepFailure:  #pragma: no cover
        # Mark the step as an INFRA_FAILURE and get the output
        # properties of underlying recipes.
        presentation.status = 'EXCEPTION'
        hw_tests = self.m.buildbucket.get_multi([task_id])[task_id]

      results = []
      responses = self._get_multi_response_binary(hw_tests)
      for t in tasks:
        result = responses.get(
            _request_tag(t.test), self._default_failed_response())
        results.append(self._translate_result(result, t))

      presentation.logs['return value'] = [str(r) for r in results]
      return results

  def _get_multi_response_binary(self, build):
    try:
      resps = build.output.properties['compressed_responses']
    except ValueError:
      return ExecuteResponses().tagged_responses
    wire_format = resps.decode('base64_codec').decode('zlib_codec')
    responses = ExecuteResponses.FromString(wire_format)
    return responses.tagged_responses

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
