# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import zlib

from typing import List
from RECIPE_MODULES.chromeos.skylab import structs
from google.protobuf import json_format

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.lab import license as license_pb2
from PB.test_platform.request import Request
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState
from recipe_engine import recipe_api


class SkylabApi(recipe_api.RecipeApi):
  """Module for issuing commands to Skylab"""

  SkylabTask = structs.SkylabTask
  SkylabResult = structs.SkylabResult
  UnitHwTest = structs.UnitHwTest

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'
    self._ctp_builder = str(properties.ctp_builder) or 'cros_test_platform'
    self._exclude_sub_invs = properties.exclude_sub_invs

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  def set_qs_account(self, qs_account):
    """Override the quota scheduler account at runtime."""
    self._qs_account = qs_account

  def schedule_ctp_requests(self, tagged_requests, can_outlive_parent=True,
                            bb_tags=None, **kwargs):
    """Schedule a cros_test_platform build.

    Args:
      tagged_requests (dict): Dictionary of string to test_platform.Request
        objects.
      can_outlive_parent (bool): Whether this build can outlive its parent. The
        default is True.
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

    props = {'requests': tagged_requests}
    if self._exclude_sub_invs:
      # If the CTP build we are scheduling is not going to become an included
      # invocation of the current build, it should mark itself for ResultDB
      # export.
      props['force_export'] = True
    bb_request = self.m.buildbucket.schedule_request(
        self._ctp_builder,
        bucket='testplatform',
        properties=props,
        tags=bb_tags if bb_tags else [],
        experiments=exps,
        # TODO(b/186217519,b/186218358): Pass in gerrit_changes and
        # gitiles_commit from src_state to create CTP tile. Relying on buildset
        # tags here is incorrect according to buildbucket V2.
        gerrit_changes=self.m.src_state.gerrit_changes,
        can_outlive_parent=can_outlive_parent,
        swarming_parent_run_id=self.m.swarming.task_id
        if not can_outlive_parent else None,
        # Disable inheriting the version from the parent builder.
        exe_cipd_version='',
        **kwargs)
    return self.m.buildbucket.schedule(
        [bb_request], include_sub_invs=not self._exclude_sub_invs)[0]

  def schedule_suites(self, unit_hw_tests, timeout, name=None,
                      async_suite_run=False, container_metadata=None,
                      require_stable_devices=False):
    """Schedule HW test suites by invoking the cros_test_platform recipe.

    Args:
    * unit_hw_tests (list[UnitHwTest]): Hardware test suites to execute
    * timeout (Duration): Timeout in timestamp_pb2.Duration.
    * name (str): The step name. Defaults to 'schedule skylab tests v2'
    * async_suite_run (bool): If set, indicates that caller does not intend to wait for
      the scheduled suites to complete, and the child build can outlive the parent build.
    * container_metadata (ContainerMetadata): Information on container
        images used for test execution.
    * require_stable_devices (bool): If set, only run on devices with
        label-device-stable: True

    Returns:
      list[SkylabTask]: with buildbucket_id of the recipe launched.
    """

    def create_test_request(uht):
      """Create test Request message from UnitHwTest instance

      Args:
        uht (UnitHwTest): Hardware test suite configuration to execute

      Return
        Request instance for test that can be scheduled.
      """
      req = Request()
      req.params.hardware_attributes.model = uht.hw_test.skylab_model
      req.params.hardware_attributes.require_stable_device = require_stable_devices
      req.params.time.maximum_duration.seconds = timeout.seconds
      image_path = uht.unit.common.build_payload.artifacts_gs_path
      image_bucket = uht.unit.common.build_payload.artifacts_gs_bucket
      gs_url = ('gs://' + image_bucket + '/' + image_path)
      req.params.metadata.test_metadata_url = gs_url
      req.params.metadata.debug_symbols_archive_url = gs_url
      container_metadata_info = self.m.metadata.METADATA_PAYLOADS['container']
      req.params.metadata.container_metadata_url = self.m.metadata.gspath(
          container_metadata_info, image_bucket, image_path)
      self._set_pool(req.params.scheduling, uht.hw_test.pool)
      sw_dep = req.params.software_dependencies.add()
      sw_dep.chromeos_build = image_path
      sw_dep_gsc_bucket = req.params.software_dependencies.add()
      sw_dep_gsc_bucket.chromeos_build_gcs_bucket = image_bucket
      req.params.scheduling.qs_account = self._qs_account
      if uht.hw_test.common.critical.value:
        req.params.test_execution_behavior = (
            Request.Params.TestExecutionBehavior.CRITICAL)
      else:
        req.params.test_execution_behavior = (
            Request.Params.TestExecutionBehavior.NON_CRITICAL)
      req.params.software_attributes.build_target.name = uht.hw_test.skylab_board
      suite_to_create = req.test_plan.suite.add()
      suite_to_create.name = uht.hw_test.suite
      self._set_license_labels(req, uht.hw_test.licenses)

      tags = self._get_ctp_tags(uht.hw_test, image_path)
      request_tags = ['{}:{}'.format(key, value) for key, value in tags.items()]
      req.params.decorations.tags.extend(request_tags)

      release_autotest_keyvals = self._get_release_autotest_keyvals(uht)
      if release_autotest_keyvals:
        for k, v in release_autotest_keyvals.items():
          req.params.decorations.autotest_keyvals[k] = v

      resultdb_autotest_keyvals = self._get_resultdb_autotest_keyvals(uht)
      if resultdb_autotest_keyvals:
        for k, v in resultdb_autotest_keyvals.items():
          req.params.decorations.autotest_keyvals[k] = v

      self._enable_test_retries(req)

      return req

    ####
    # Start of main body
    have_container_metadata = container_metadata is not None

    name = name or 'schedule skylab tests v2'
    with self.m.step.nest(name) as presentation:
      presentation.logs['container metadata'] = [
          json_format.MessageToJson(container_metadata)
      ] if have_container_metadata else '{}'

      # str -> (Request dict)
      reqs = {}
      with self.m.step.nest('create test requests'):
        for uht in unit_hw_tests:
          step_name = 'configure {}'.format(uht.unit.common.builder_name)
          skylab_board = uht.hw_test.skylab_board
          if skylab_board != uht.unit.common.build_target.name:
            step_name = step_name + ' ({})'.format(skylab_board)
          with self.m.step.nest(step_name) as configure_step:
            request = create_test_request(uht)

            # If a test config has run_via_cft set, then check that we have
            # container metadata for the build target we're testing, and set run_via_cft
            # in the Request's execution parameters.
            if uht.hw_test.run_via_cft:
              build_target = uht.unit.common.build_target.name

              if (not have_container_metadata or
                  not build_target in container_metadata.containers):
                configure_step.status = self.m.step.FAILURE
                configure_step.step_summary_text = \
                  "Execution via container requested, " + \
                  "but no container metadata for build target '{}'".format(build_target)
                continue
              request.params.run_via_cft = True
              request.params.run_via_trv2 = uht.hw_test.run_via_trv2
              request.params.trv2_steps_config.CopyFrom(
                  uht.hw_test.trv2_steps_config)
              request.test_plan.tag_criteria.CopyFrom(uht.hw_test.tag_criteria)
              configure_step.step_summary_text = "(Executing via CFT)"

            configure_step.logs['request'] = [
                json_format.MessageToJson(request)
            ]
            reqs[_request_tag(uht.hw_test)] = json_format.MessageToDict(request)

      bb_tags = self.m.cros_tags.make_schedule_tags(
          self.m.cros_infra_config.gitiles_commit, inherit_buildsets=True)
      build = self.schedule_ctp_requests(tagged_requests=reqs,
                                         can_outlive_parent=async_suite_run,
                                         bb_tags=bb_tags,
                                         inherit_buildsets=False)

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

  def _get_resultdb_autotest_keyvals(self, uht):
    return {'build_target': uht.unit.common.build_target.name}

  def _get_release_autotest_keyvals(self, uht):
    builder_name = uht.unit.common.builder_name

    config = self.m.cros_infra_config.config
    if not (config and config.id.type == BuilderConfig.Id.RELEASE):
      return None

    # Drop everything after '-release'.
    build_config = builder_name
    if '-release' in build_config:
      build_config = builder_name[:builder_name.index('-release') + 8]

    result = {
        'branch': self.m.cros_source.manifest_branch,
        'build_config': build_config,
        'cidb_build_id': str(self.m.buildbucket.build.id),
        # TODO(b/228878300): GE needs `master_build_config` to see the test.
        # Remove when possible (COIL).
        'master_build_config': 'master-release',
    }
    return result

  def _enable_test_retries(self, req):
    """Enable test retries within suites.

    Args:
      params: A request.Request object.
    """
    req.params.retry.max = 30
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
      # Get a list of the unique Buildbucket ids for skylab tasks.
      task_ids = list(set(task.id for task in tasks))
      # Give 30 minutes grace period for recipes to time out.
      timeout_seconds = int(timeout.seconds + 30 * 60)
      try:
        hw_test_builds = self.m.buildbucket.collect_builds(
            task_ids, timeout=timeout_seconds)
      except recipe_api.StepFailure:  #pragma: no cover
        # Mark the step as an INFRA_FAILURE and get the output
        # properties of underlying recipes.
        presentation.status = 'EXCEPTION'
        hw_test_builds = self.m.buildbucket.get_multi(task_ids)

      results = []
      responses = {}
      for build in hw_test_builds.values():
        responses.update(self._get_multi_response_binary(build))
      for t in tasks:
        result = responses.get(
            _request_tag(t.test), self._default_failed_response())
        results.append(self._translate_result(result, t))

      self.m.greenness.update_hwtest_info(results)
      presentation.logs['return value'] = [str(r) for r in results]
      return results

  def get_previous_results(self, task_ids: List[str],
                           unit_hw_tests: List[structs.UnitHwTest]
                          ) -> List[structs.SkylabResult]:
    """Get the results from the previous tasks with the specified task_ids.

    Args:
      task_ids: The list of Skylab task IDs for which to retrieve results.
      unit_hw_tests: The list of unit_hw_tests for which to retrieve results.

    Returns:
      The list of Skylab results for the specified unit_hw_tests that ran in
      the tasks with the specified task_ids.
    """
    with self.m.step.nest('get previous skylab tasks v2'):
      hw_test_builds = self.m.buildbucket.get_multi(task_ids)
      results = []
      for build in hw_test_builds.values():
        build_url = self.m.buildbucket.build_url(build_id=build.id)
        response = self._get_multi_response_binary(build)
        for uht in unit_hw_tests:
          disp_name = _request_tag(uht.hw_test)
          if disp_name in response:
            result = response.get(disp_name)
            task = self.SkylabTask(id=build.id, url=build_url, test=uht.hw_test,
                                   unit=uht.unit)
            results.append(self._translate_result(result, task))
      return results

  def _get_multi_response_binary(self, build):
    try:
      resps = build.output.properties['compressed_responses']
    except ValueError:
      return ExecuteResponses().tagged_responses
    wire_format = zlib.decompress(base64.b64decode(resps))
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
