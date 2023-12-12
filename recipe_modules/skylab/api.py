# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for issuing commands to Skylab"""

import re
from typing import Dict, List

from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabTask, UnitHwTest
from RECIPE_MODULES.chromeos.cros_history.api import TERMINAL_STATUSES
from google.protobuf.duration_pb2 import Duration
from google.protobuf import json_format

from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.test.api.test_suite import TestSuite
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.lab import license as license_pb2
from PB.test_platform.request import Request
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from recipe_engine import recipe_api

_DEFAULT_FAILED_RESPONSE = ExecuteResponse(
    state=TaskState(verdict=TaskState.VERDICT_FAILED,
                    life_cycle=TaskState.LIFE_CYCLE_COMPLETED))

_TAST_FIRST_CLASS_TESTS_OUTPUT_PROP = 'tast_first_class_tests'

TESTING_OVERRIDE_FOOTER = 'Testing-Override'


class SkylabApi(recipe_api.RecipeApi):

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'
    self._ctp_builder = str(properties.ctp_builder) or 'cros_test_platform'
    self._exclude_sub_invs = properties.exclude_sub_invs
    self._last_run_tast_first_class_tests = None

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  # A 'Testing-Override' git footer value pattern.
  QS_UNMANAGED_PATTERN = 'p[0-3]_cq_unmanaged'

  @property
  def qs_account(self):
    """Get the quota scheduler account the module is configured to use."""
    return self._qs_account

  def set_qs_account(self, qs_account):
    """Override the quota scheduler account at runtime."""
    self._qs_account = qs_account

  def apply_qs_account_overrides(self, gerrit_changes: List[GerritChange]):
    """Apply any QS account overrides the build is elegible for.

    Currently supports overriding the account if any of the Gerrit Changes have
    the 'Testing-Override' footer or if the current build is testing Chrome
    PUpr CL.

    Args:
      gerrit_changes: The gerrit changes applied to the build.
    """

    with self.m.step.nest('apply qs account overrides') as presentation:
      testing_override_values = self.m.git_footers.get_footer_values(
          gerrit_changes, TESTING_OVERRIDE_FOOTER)

      # Buganizer id must be at least 9 digits long.
      regex = re.compile('^(?P<qs_account>' + self.QS_UNMANAGED_PATTERN +
                         r')\s+b/\d{9,}\s*$')

      # Pick up only values matching the pattern.
      qs_accounts = []
      for testing_override_value in testing_override_values:
        for match in [regex.search(testing_override_value)]:
          if match:
            qs_accounts.append(match.group('qs_account'))

      if qs_accounts:
        qs_account = sorted(qs_accounts, reverse=True).pop()

      # Is the build tagged as overriding the PCQ quota scheduler account?
      elif self.m.cros_tags.has_entry('cq_cl_tag',
                                      'pupr:chromeos-base/lacros-ash-atomic',
                                      self.m.buildbucket.build.tags):
        qs_account = 'pupr'
      else:
        qs_account = None

      if qs_account:
        self.set_qs_account(qs_account)
        presentation.step_text = 'Applied qs account overrides: {}'.format(
            qs_account)
      else:
        presentation.step_text = 'No qs account overrides were applied'

  @property
  def last_run_tast_first_class_tests(self) -> List[str]:
    """Returns the hw tests which ran as Tast first class in the last run."""
    if self._last_run_tast_first_class_tests is not None:
      return self._last_run_tast_first_class_tests

    # Get the output property from the last orchestrator.
    prev_orch = self.m.cros_history.get_matching_builds(
        self.m.buildbucket.build, statuses=TERMINAL_STATUSES, limit=1)
    build_output = json_format.MessageToDict(
        prev_orch[0].output.properties) if len(prev_orch) > 0 else {}
    self._last_run_tast_first_class_tests = build_output.get(
        _TAST_FIRST_CLASS_TESTS_OUTPUT_PROP, [])

    return self._last_run_tast_first_class_tests

  def _direct_test_retries_elegible(self, uht: UnitHwTest,
                                    tast_first_class: bool) -> bool:
    """Returns whether the hw test is elegible for direct test retries."""

    tast_first_class_last_run = (
        self.m.skylab_results.request_tag(uht.hw_test)
        in self.last_run_tast_first_class_tests)
    return tast_first_class == tast_first_class_last_run

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

    props = self.m.cq.props_for_child_build
    props.update({'requests': tagged_requests})
    # If the orchestrator is watched by a sheriff rotation, populate in CTP.
    if 'sheriff_rotations' in self.m.buildbucket.build.input.properties:
      props.update({
          'sheriff_rotations':
              self.m.buildbucket.build.input.properties['sheriff_rotations']
      })
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

  def schedule_suites(
      self, unit_hw_tests: List[UnitHwTest], timeout: Duration,
      name: str = None, async_suite_run: bool = False,
      container_metadata: ContainerMetadata = None,
      require_stable_devices: bool = False,
      previous_results: Dict[str, ExecuteResponse] = None,
      build_target_critical_allowlist: List[str] = None) -> List[SkylabTask]:
    """Schedule HW test suites by invoking the cros_test_platform recipe.

    Args:
      unit_hw_tests: Hardware test suites to execute
      timeout: Timeout in timestamp_pb2.Duration.
      name: The step name. Defaults to 'schedule skylab tests v2'
      async_suite_run: If set, indicates that caller does not intend to wait for
          the scheduled suites to complete, and the child build can outlive the
          parent build.
      container_metadata: Information on container images used for test
          execution.
      require_stable_devices (bool): If set, only run on devices with
          'label-device-stable: True'
      previous_results: The results of the previous invocation. The results are
          a dict mapping the unit_hw_test's display name to an ExecuteResponse.
      build_target_critical_allowlist: If set (including empty list), only the
        build targets specified can have tests run as critical. If None,
        criticality will not be modified for any build targets.

    Returns:
      A list of SkylabTasks with buildbucket_id of the recipe launched.
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
      # Check companions
      primary_dut_board = uht.hw_test.skylab_board
      for companion in uht.hw_test.companions:
        comp_dev = req.params.secondary_devices.add()
        comp_dev.software_attributes.build_target.name = companion.board
        if companion.config.WhichOneof('config') == 'android':
          # Android provision is only supported by Test Runner v2
          req.params.run_via_trv2 = True
          if companion.config.android.android_image_version:
            cd_sw_dep_android = comp_dev.software_dependencies.add()
            cd_sw_dep_android.android_image_version = companion.config.android.android_image_version
          if companion.config.android.gms_core_package:
            cd_sw_dep_gms = comp_dev.software_dependencies.add()
            cd_sw_dep_gms.gms_core_package = companion.config.android.gms_core_package
        else:
          if companion.board != primary_dut_board:
            raise recipe_api.StepFailure(
                'Companion board is different from the primary device')
          # Directly use the image artifact same as the primary dut. This needs
          # change when adding support of companion board different from primary
          cd_sw_dep_build = comp_dev.software_dependencies.add()
          cd_sw_dep_build.chromeos_build = image_path
          cd_sw_dep_gcs_bucket = comp_dev.software_dependencies.add()
          cd_sw_dep_gcs_bucket.chromeos_build_gcs_bucket = image_bucket

      allow_critical = True
      if build_target_critical_allowlist is not None and uht.unit.common.build_target.name not in build_target_critical_allowlist:
        allow_critical = False

      if uht.hw_test.common.critical.value and allow_critical:
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

      if re.search(self.QS_UNMANAGED_PATTERN, self._qs_account):
        req.params.decorations.tags.append('label-quota-account:{}'.format(
            self._qs_account))

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
    previous_results = previous_results or {}
    tast_first_class_tests = []
    count_direct_test_retry_tests = 0

    name = name or 'schedule skylab tests v2'
    with self.m.step.nest(name) as presentation:
      presentation.logs['container metadata'] = json_format.MessageToJson(
          container_metadata) if have_container_metadata else '{}'

      # str -> (Request dict)
      reqs = {}
      suiteReqCount = {}
      with self.m.step.nest('create test requests'):
        for uht in unit_hw_tests:
          step_name = 'configure {}'.format(uht.unit.common.builder_name)
          skylab_board = uht.hw_test.skylab_board
          if skylab_board != uht.unit.common.build_target.name:
            step_name = step_name + ' ({})'.format(skylab_board)
          with self.m.step.nest(step_name) as configure_step:
            request = create_test_request(uht)

            tast_first_class = False
            # If a test config has run_via_cft set, then check that we have
            # container metadata for the build target we're testing, and set run_via_cft
            # in the Request's execution parameters.
            if uht.hw_test.run_via_cft:
              build_target = uht.unit.common.build_target.name

              if (not have_container_metadata or
                  not build_target in container_metadata.containers):
                configure_step.status = self.m.step.FAILURE
                configure_step.step_summary_text = \
                  'Execution via container requested, ' + \
                  "but no container metadata for build target '{}'".format(build_target)
                continue
              request.params.run_via_cft = True
              # Use trv2 when it is required by android companion or configured
              request.params.run_via_trv2 = request.params.run_via_trv2 or uht.hw_test.run_via_trv2
              request.params.trv2_steps_config.CopyFrom(
                  uht.hw_test.trv2_steps_config)
              request.test_plan.tag_criteria.CopyFrom(uht.hw_test.tag_criteria)
              if uht.hw_test.tag_criteria != TestSuite.TestCaseTagCriteria():
                tast_first_class = True
                tast_first_class_tests.append(
                    self.m.skylab_results.request_tag(uht.hw_test))
                request.test_plan.total_shards = uht.hw_test.total_shards
              configure_step.step_summary_text = '(Executing via CFT)'

              # Only pass the names of previously failed tests if the run is
              # elegible for direct tast testing.
              # TODO(b/271938042): Remove gating after the rollout is complete.
              if self._direct_test_retries_elegible(uht, tast_first_class):
                previous_result = previous_results.get(
                    self.m.skylab_results.request_tag(uht.hw_test),
                    ExecuteResponse())
                test_cases = self._tests_to_retry(previous_result,
                                                  tast_first_class)
                if test_cases:
                  count_direct_test_retry_tests += 1
                for t in test_cases or []:
                  test_case = request.test_plan.test.add()
                  test_case.autotest.name = t

            configure_step.logs['request'] = json_format.MessageToJson(request)

            key = self.m.skylab_results.request_tag(uht.hw_test)
            if key in reqs:
              if key not in suiteReqCount:
                suiteReqCount[key] = 1
              suiteReqCount[key] += 1
              key += '_{}'.format(suiteReqCount[key])
            reqs[key] = json_format.MessageToDict(request)

      # It is possible no reqs were actually added, e.g. if no containers are
      # found. Exit early instead of scheduling a pointless CTP build.
      if not reqs:
        return []

      bb_tags = self.m.cros_tags.make_schedule_tags(
          self.m.cros_infra_config.gitiles_commit, inherit_buildsets=True)
      build = self.schedule_ctp_requests(tagged_requests=reqs,
                                         can_outlive_parent=async_suite_run,
                                         bb_tags=bb_tags,
                                         inherit_buildsets=False)
      presentation.properties[
          _TAST_FIRST_CLASS_TESTS_OUTPUT_PROP] = tast_first_class_tests
      presentation.properties[
          'count_direct_test_retry_tests'] = count_direct_test_retry_tests

      build_url = self.m.buildbucket.build_url(build_id=build.id)
      presentation.links['suite link'] = build_url

      tasks = []
      for uht in unit_hw_tests:
        tasks.append(
            SkylabTask(id=build.id, url=build_url, test=uht.hw_test,
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
      dimension = 'label-license:' + license_pb2.LicenseType.Name(lic)
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

  def _tests_to_retry(self, response: ExecuteResponse,
                      tast_first_class: bool = False) -> List[str]:
    """Returns the names of the failed tests that should be directly retried.

    If the test suite is running Tast first class, then return the names of the
    failed test cases; otherwise return the names of the failed task results.

    Args:
      response: The result from which to get the failed tests names.
      tast_first_class: Whether the suite is running Tast first class.

    Returns:
      The names of the tests to retry.
    """
    if len(response.task_results) == 0:
      return []

    if tast_first_class:
      return self.m.skylab_results.extract_failed_test_case_names(
          response.task_results)

    return self.m.skylab_results.extract_failed_test_shard_names(
        response.task_results)

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
        responses.update(
            self.m.skylab_results.get_tagged_execute_responses_from_build(
                build))
      for t in tasks:
        result = responses.get(
            self.m.skylab_results.request_tag(t.test), _DEFAULT_FAILED_RESPONSE)
        results.append(self.m.skylab_results.translate_result(result, t))

      self.m.greenness.update_hwtest_info(results)
      presentation.logs['return value'] = [str(r) for r in results]
      return results
