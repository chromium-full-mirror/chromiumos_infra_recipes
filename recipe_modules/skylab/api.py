# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from . import structs

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.lab import license as license_pb2
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
    self._resultdb_elegible_projects = properties.resultdb_elegible_projects
    self._enable_container_support = properties.enable_container_support

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  @property
  def resultdb_elegible_projects(self):
    """Returns the names of the repos elegible for go/cros-gerrit-results."""
    return self._resultdb_elegible_projects

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
    # TODO(b/201608160): Enable uploading to resultdb on select repos.
    # Remove check for repos and experiment upon experiment conclusion.
    if self._resultdb_elegible_projects and all(
        x.project in self._resultdb_elegible_projects
        for x in self.m.src_state.gerrit_changes):
      exps.update({'chromeos.cros_test_platform.add_resultdb_settings': True})

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
                      async_suite_run=False, container_metadata=None,
                      require_stable_devices=False):
    """Schedule HW test suites by invoking the cros_test_platform recipe.

    Args:
    * tests (list[UnitHwTest]): Hardware test suites to execute
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
      req.params.hardware_attributes.model = ''
      req.params.hardware_attributes.require_stable_device = require_stable_devices
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
      if self._enable_retries:
        self._enable_test_retries(req)

      return req

    ####
    # Start of main body

    # Unless we're specifically opted-in to container support, ignore container
    # metadata.
    if not self._enable_container_support:
      container_metadata = None
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

            # If container execution support is enabled, then we can handle
            # requests to opt-in test execution via containers.
            #
            # If a test config has run_via_container set, then check that we have
            # container metadata for the build target we're testing, and pass it
            # through via the Request's execution parameters.
            if self._enable_container_support and uht.hw_test.run_via_container:
              build_target = uht.unit.common.build_target.name

              if (not have_container_metadata or
                  not build_target in container_metadata.containers):
                configure_step.status = self.m.step.FAILURE
                configure_step.step_summary_text = \
                  "Execution via container requested, " + \
                  "but no container metadata for build target '{}'".format(build_target)
                continue
              else:
                configure_step.step_summary_text = "(Executing via container)"

              # The 'cros-test' container contains the autoserv binary we'll use
              container_image_map = container_metadata.containers[build_target]
              request.params.execution_param.container_image_info.CopyFrom(
                  container_image_map.images['cros-test'],
              )

            configure_step.logs['request'] = [
                json_format.MessageToJson(request)
            ]
            reqs[_request_tag(uht.hw_test)] = json_format.MessageToDict(request)

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

      self.m.greenness.update_hwtest_info(results)
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
