# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""dut_interface for cros_tool_runner."""

from collections import namedtuple
from collections import defaultdict
import traceback

from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from google.protobuf.any_pb2 import Any

from RECIPE_MODULES.chromeos.dut_interface.crostoolrunner_results import CrosToolRunnerResult, CrosToolRunnerPrejobDUTResponse, CrosToolRunnerTestDUTResponse

from RECIPE_MODULES.chromeos.dut_interface import dut_interface

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.chromiumos.test.api import post_test_service as post_request
from PB.chromiumos.test.api import test_execution_metadata as Test_Execution_Metadata
from PB.chromiumos.test.api.test_case_metadata import TestCaseMetadataList
from PB.chromiumos.test.lab import api as lab_api
from PB.test_platform import phosphorus
from PB.test_platform.skylab_local_state.load import Dut as LoadDut
from PB.test_platform.skylab_local_state.load import LoadResponse
from PB.test_platform.skylab_test_runner.result import Result as Skylab_Result
from PB.chromiumos.test import api as ctr_api
from PB.test_platform.request import Request

from recipe_engine.recipe_api import StepFailure

RunTestResponsesTuple = namedtuple('RunTestResponsesTuple',
                                   ['test_dut_responses', 'any_test_failed'])
PrejobResponsesTuple = namedtuple(
    'PrejobResponsesTuple',
    ['prejob_dut_responses', 'any_provision_failed', 'failure_reason'])

HOUR = 60 * 60

TestResultVisibility = Request.Params.ResultsUploadConfig.TestResultsUploadVisibility


class CrosToolRunnerTestMetadata(dut_interface.DUTTestMetadata
                                ):  # pragma: no cover
  """
  Holds metadata specific to one test or a group of tests.
  Passable to DutInterface that requires info from this class to provision, run tests etc.
  """

  def __init__(self, interface, test_id, test, cft_test_request,
               autotest_keyvals=None, artifact_dir='', image_storage_server='',
               invocation_id=''):
    """Specific constructor for CrosToolRunner subclass of DUTTestMetadata

    Args:
    * interface (CrosToolRunnerInterface):
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    * image_storage_server (str): Image storage server info.
    * invocation_id (str): Invocation id of the test run.
    """
    super().__init__(test_id=test_id, test=test, gs_url=interface.logs_gs_url(),
                     image_storage_server=image_storage_server,
                     invocation_id=invocation_id)

    self.artifact_dir = artifact_dir
    self.autotest_keyvals = autotest_keyvals
    self.load_response = interface.load_skylab_local_state(
        test=test, test_id=test_id)

    undesignated_duts = [
        dut for topology in self.load_response.lab_dut_topology
        for dut in topology.duts
    ]
    # Match requested cft_test_request devices to duts from topology.
    # Start with requested primary device.
    self.primary_dut = self.match_dut(undesignated_duts,
                                      cft_test_request.primary_dut)
    self.peer_duts = []
    self.peer_provision_states = []
    for dut in cft_test_request.companion_duts:
      match = self.match_dut(undesignated_duts, dut)
      if match is None:
        continue
      self.peer_duts.append(match)
      self.peer_provision_states.append(dut.provision_state)

    # Unix time of when test execution finished. Used to be passed via keyvals for autotests.
    self.job_finished = 0
    # Info used in rdb upload.
    self.rdb_base_tags = None
    self.rdb_base_variant = None
    self.rdb_sources_file = None

  def match_dut(self, dut_pool, requested_device):
    """Find a match to the requested build_target/model pair inside the dut_pool.

    Args:
    * dut_pool ([]lab.Dut): List of available duts for matching.
    * request_device (skylab_test_runner.CrosTest_Device): Device to be matched.

    Returns: lab.Dut that matches to the build_target/model pair of requested_device.
    """
    request_key = requested_device.dut_model.build_target + '_' + requested_device.dut_model.model_name
    found_index = -1
    for i, dut in enumerate(dut_pool):
      dut_typed = None
      if dut.WhichOneof('dut_type') == 'chromeos':
        dut_typed = dut.chromeos
      elif dut.WhichOneof('dut_type') == 'android':
        dut_typed = dut.android
      if dut_typed is None:
        continue
      dut_key = dut_typed.dut_model.build_target + '_' + dut_typed.dut_model.model_name
      if request_key in dut_key:
        found_index = i
        break
    # No match
    if found_index == -1:
      return None

    match = dut_pool[found_index]
    del dut_pool[found_index]
    return match


class CrosToolRunnerInterface(dut_interface.DUTInterface):  # pragma: no cover

  ARTIFACT_DIR_PREFIX = 'output_dir'
  KEYVAL_FILENAME = 'keyval'
  TEST_HARNESS_TAUTO = 'tauto'
  TEST_HARNESS_TAST = 'tast'
  AUTOTEST_PACKAGE_PATH = '/usr/local/autotest'
  TAST_MISSING_TEST_KEY = 'tast_missing_test'
  TAST_TEST_NAME_PREFIX = 'tast.'
  RESULTS_DIR_NAME = 'results'
  ARTIFACT_DIR_NAME = 'artifact'
  TEST_METADATA_JSON = 'test_metadata.json'
  TEST_RUNNER_RESULT_JSON = 'test_runner_result.json'
  STREAMED_RESULTS_JSON = 'streamed_results.jsonl'

  # TODO(fqj): Remove once InventoryServer can have FakeDut.
  FAKE_LOAD_RESPONSE_FOR_BETTY = LoadResponse(
      dut_topology=[
          LoadDut(
              board='betty',
              model='betty',
              hostname='fake_dut',
          )
      ],
      lab_dut_topology=[
          lab_api.dut.DutTopology(duts=[
              lab_api.dut.Dut(
                  id=lab_api.dut.Dut.Id(
                      value='fake_dut'), cache_server=lab_api.dut.CacheServer(
                          address=lab_api.ip_endpoint.IpEndpoint(
                              address='0.0.0.0', port=8080)),
                  chromeos=lab_api.dut.Dut.ChromeOS(
                      dut_model=lab_api.dut.DutModel(
                          build_target='betty', model_name='betty'), ssh=lab_api
                      .ip_endpoint.IpEndpoint(address='fake_host', port=22)))
          ])
      ],
  )
  USE_FAKE_LOAD_RESPONSE_FOR_BETTY = True

  def __init__(self, api, properties):
    """DUTInterface implementation with cros-tool-runner.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API.
    * properties (TestRunnerProperties): Input properties to the recipe.
    """
    super().__init__(api, properties)
    self.cft_test_request = self._properties.cft_test_request
    self._vm_provisioned = None

  def _vm_is_vmtest(self):
    """Checks if it qualifies VM testing.

    Returns:
      True if this should run via GCE.
    """

    # TODO(b/243367000): Check self.cft_test_request.test_suites[0].name
    # instead.
    check_suite = 'cheets_CTS_' in self.cft_test_request.test_suites[
        0].test_case_ids.test_case_ids[0].value
    is_betty = self.cft_test_request.autotest_keyvals['build'].startswith(
        'betty')
    # Excludes betty and betty-pi-arc.
    check_image = self.cft_test_request.autotest_keyvals['build'].startswith(
        'betty-arc-')
    if is_betty and not check_image:
      raise self._api.step.StepFailure(
          'betty and betty-pi-arc is not supported.')
    if check_image and not check_suite:
      raise self._api.step.StepFailure('betty can only run CTS at this moment.')
    return check_suite and check_image

  # TODO(fqj, b/236679125): This is prototype hack, which breaks CFT
  # reproducibility. Migrate to CFT services.
  def _vm_direct_provision(self, metadata):
    """Directly provision VM from GCP

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      PrejobResponsesTuple: The prejob responses in ['prejob_dut_responses', 'any_provision_failed'] tuple.

    Raises:
      * api.test.StepFailure if prejob fails.
    """
    suffix = self._api.buildbucket.build.id
    if suffix == 0:
      # LED runs have buildbucket id=0. Use a random number.
      self._api.random.seed(int(self._api.time.time()))
      suffix = self._api.random.randint(1000000, 9999999)

    build = metadata.autotest_keyvals['build']
    # Hack: for minimum code change, access bot_id from cros_tool_runner, rather
    # than setting up env_vars/metadata for crostoolrunner_interface
    # TODO(b/250615010): clean ups.
    bot_name = self._api.cros_tool_runner.bot_id

    self._vm_provisioned = {}

    self._api.vmlab.cleanup_vm('clean up orphan instances', 'cts-prototype',
                               swarming_bot_name=bot_name, allow_failure=True)

    image_info = self._api.vmlab.import_image('create image', build, wait=True,
                                              assert_ready=True)

    instance_created = self._api.vmlab.lease_vm(
        'create instance', 'cts-prototype', image_info['name'],
        image_project=image_info['project'], swarming_bot_name=bot_name)
    instance_name, ssh = instance_created['name'], instance_created['ssh']
    self._vm_provisioned['instance_name'] = instance_name

    self._api.step('wait for betty boots', [
        '/usr/bin/ssh', '-o', 'StrictHostKeyChecking=no', '-o',
        'UserKnownHostsFile=/dev/null', '-o', 'BatchMode=yes',
        'root@' + ssh['address'], 'true'
    ])

    metadata.primary_dut.chromeos.ssh.address = ssh['address']
    metadata.primary_dut.chromeos.ssh.port = ssh['port']

    return PrejobResponsesTuple([], False, '')

  def _vm_shutdown_and_cleanup(self):
    """Shutsdown and cleanup environment on GCE."""

    if not self._vm_provisioned:
      return

    if 'instance_name' in self._vm_provisioned:
      self._api.vmlab.delete_vm('delete instance', 'cts-prototype',
                                self._vm_provisioned['instance_name'])

  def submit_post_job(self):
    """Submits a Postjob for VM"""

    if not self._vm_is_vmtest():
      return

    with self._api.step.nest('Prototype GCE shutdown'):
      self._vm_shutdown_and_cleanup()

  def submit_pre_job(self, metadata, max_duration_seconds):
    """Submits a Prejob execution on the DUT.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * max_duration_seconds (int): The longest amount of time this test may run. (Not used)

    Returns:
      PrejobResponsesTuple: The prejob responses in ['prejob_dut_responses', 'any_provision_failed'] tuple.

    Raises:
      * api.test.StepFailure If prejob fails.
    """

    if self._vm_is_vmtest():
      with self._api.step.nest('Prototype GCE provision') as step:
        return self._vm_direct_provision(metadata)
    with self._api.step.nest('CrosToolRunner: run provision') as step:
      deadline = self._get_context_deadline(max_duration_seconds, step)
      try:
        with self._api.context(infra_steps=True, deadline=deadline):
          self.cft_test_request.primary_dut.provision_state.update_firmware = \
            self.should_update_os_bundled_firmware(self.cft_test_request.primary_dut)
          for companion in self.cft_test_request.companion_duts:
            companion.provision_state.update_firmware = self.should_update_os_bundled_firmware(
                companion)

          provision_request = ctr.CrosToolRunnerProvisionRequest(
              devices=self.get_provision_devices(metadata))
          prejob_response = self._process_prejob_response(
              self._api.cros_tool_runner.provision(provision_request))

          if prejob_response.any_provision_failed:
            step.presentation.status = self._api.step.FAILURE
            step.presentation.step_summary_text = prejob_response.failure_reason
            step.presentation.tags[
                'provision_failure'] = prejob_response.failure_reason

          return prejob_response
      except StepFailure as e:  # pragma: nocover
        if (e.exc_result is not None and e.exc_result.had_timeout):
          # This will make sure that the failure doesn't incorrectly present as an
          # infra_failure. We don't want to present an infra_failure because
          # nothing on our end has gone wrong and this will shield us from
          # potential misfiled bugs.
          step.presentation.staus = self._api.step.FAILURE
          e = StepFailure('Prejob execution time limit of %.1f hours reached' %
                          (max_duration_seconds / HOUR))
        raise e

  def get_provision_devices(self, metadata):
    """Gather the provisionable devices by matching requested boards to metadata.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      devices: [ctr.CrosToolRunnerProvisionRequest.Device]
    """
    devices = [
        ctr.CrosToolRunnerProvisionRequest.Device(
            dut=metadata.primary_dut,
            provision_state=self.cft_test_request.primary_dut.provision_state,
            container_metadata_key=self.cft_test_request.primary_dut
            .container_metadata_key)
    ]
    devices.extend([
        ctr.CrosToolRunnerProvisionRequest.Device(
            dut=dut, provision_state=metadata.peer_provision_states[i],
            container_metadata_key=self.cft_test_request.primary_dut
            .container_metadata_key) for i, dut in enumerate(metadata.peer_duts)
    ])

    return devices

  def run_test(self, metadata, container_image_info=None):
    """Submits a test execution on the DUT.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * container_image_info (ContainerImageInfo): If set, info on a Docker
    container for use by the DUTInterface. For example, autoserv may be run by
    the container instead of the host. (Not used)

    Returns:
      RunTestResponsesTuple: The test execution responses in ['test_dut_responses'] tuple.

    Raises:
      * api.test.StepFailure If test fails.
    """
    del container_image_info

    with self._api.step.nest('CrosToolRunner: run test') as step:
      primary_dut_device = ctr.CrosToolRunnerTestRequest.Device(
          dut=metadata.primary_dut, container_metadata_key=self.cft_test_request
          .primary_dut.container_metadata_key)
      companion_dut_devices = None
      if len(metadata.peer_duts) > 0:
        companion_dut_devices = [
            ctr.CrosToolRunnerTestRequest.Device(dut=metadata.peer_duts[0])
        ]

      test_execution_metadata_anypb = self.get_test_execution_metadata()
      run_test_request = ctr.CrosToolRunnerTestRequest(
          test_suites=self.cft_test_request.test_suites,
          primary_dut=primary_dut_device, companion_duts=companion_dut_devices,
          artifact_dir=metadata.artifact_dir,
          metadata=test_execution_metadata_anypb)
      test_response = self._process_run_test_response(
          self._api.cros_tool_runner.test(run_test_request))

      if test_response.any_test_failed:
        step.presentation.status = self._api.step.FAILURE

      return test_response

  def load_skylab_local_state(
      self, test=None, test_id=dut_interface.DUTTestMetadata.DUMMY_TEST_ID):
    """Get skylab local state from DUT for specific test(s).

    Args:
    * test (skylab_test_runner.Request.Test): The actual test request. (Not used)
    * test_id (str): The desired test to pull state from. (Not required)

    Returns:
      skylab_local_state.LoadResponse
    """
    del test

    if self._vm_is_vmtest() and self.USE_FAKE_LOAD_RESPONSE_FOR_BETTY:
      return self.FAKE_LOAD_RESPONSE_FOR_BETTY

    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: load skylab local state'):
      with self._api.context(env={'USE_DUT_TOPO': True}):
        return self._api.phosphorus.load_skylab_local_state(test_id=test_id)

  def save_skylab_local_state(self, dut_state, metadata, repair_requests=None):
    """Save skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    if self._vm_is_vmtest():
      self._api.step('stub mark local DUT state', ['echo', dut_state])
      return

    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: mark local DUT state: {}'.format(
            dut_state)):
      self._api.phosphorus.save_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.id.value,
          peer_duts=[dut.id.value for dut in metadata.peer_duts],
          repair_requests=repair_requests)

  def save_and_seal_skylab_local_state(self, dut_state, metadata,
                                       repair_requests=None):
    """Save and seal skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * repair_requests (array): Requests to enforce repair actions.
    """
    if self._vm_is_vmtest():
      self._api.step('stub save local DUT state', ['echo', dut_state])
      return

    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: save local DUT state'):
      self._api.phosphorus.save_and_seal_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.id.value,
          peer_duts=[dut.id.value for dut in metadata.peer_duts],
          repair_requests=repair_requests)

  def fetch_crashes(self, metadata, max_duration_seconds):
    """Retrieves crash information in case of a crash.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * max_duration_seconds (int): The longest amount of time this test may run.

    Returns:
      dut_results.DUTFetchCrashResponse: The crash information.

    Raises:
      * api.test.StepFailure If test fails.
    """
    raise NotImplementedError

  def upload_to_tko(self, metadata, run_test_response):
    """Uploads test information to TKO for current test.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * run_test_response (List[DUTTestResponse]): The response to the test run.

    Raises:
    * InfraFailure.
    """
    all_valid_result_dir = True
    with self._api.step.nest('CrosToolRunner: upload to TKO'):
      # Iterate through the test_dut_responses(CrosToolRunnerTestDUTResponse type).
      # Retrieve ctr_test_response(TestCaseResult type) and check which test cases are of harness type 'tauto'.
      # For 'tauto' harness type, try to upload test results to TKO.
      for test_dut_response in run_test_response:
        ctr_test_response = test_dut_response.data
        test_harness_type = ctr_test_response.test_harness.WhichOneof(
            'test_harness_type')
        results_dir = ctr_test_response.result_dir_path.path
        test_case_id = ctr_test_response.test_case_id.value
        with self._api.step.nest(test_case_id) as step:
          if test_harness_type == self.TEST_HARNESS_TAUTO:
            if self._write_to_keyvals(results_dir,
                                      self._get_updated_keyvals(metadata)):
              with self._api.context(infra_steps=True):
                self._api.cros_tool_runner.upload_to_tko(
                    autotest_dir=self.AUTOTEST_PACKAGE_PATH,
                    results_dir=results_dir)
            else:
              all_valid_result_dir = False
              step.presentation.status = self._api.step.FAILURE
          else:
            step.presentation.logs[
                'TKO upload skipped'] = "TKO upload skipped for test '{}' which is of test harness type '{}'. Only '{}' harness type is allowed for TKO upload.".format(
                    test_case_id, test_harness_type, self.TEST_HARNESS_TAUTO)
    # Try to upload all valid results to TKO before failing
    if not all_valid_result_dir:
      raise self._api.step.StepFailure('Invalid result directory found')

  def _write_to_keyvals(self, results_dir, autotest_keyvals):
    """Write autotest keyvals to keyval file.

    This is required before upload-to-tko step.
    TKO parse will read these keyvals to upload the test results properly.

    Args:
    * results_dir (str): path to results dir of the specific test.
    * autotest_keyvals (dict): autotest keyvals that needs to be added to keyval file.

    Returns:
      bool: true if write to keyval was successful; false otherwise
    """
    with self._api.step.nest('Result directory validation') as step:
      self._api.path.mock_add_paths(results_dir)
      if not self._api.path.exists(results_dir):
        # Fail this step
        step.presentation.status = self._api.step.FAILURE
        step.presentation.logs['details'] = '{} path is invalid'.format(
            results_dir)
        return False
    keyval_file_path = self._api.path.join(results_dir, self.KEYVAL_FILENAME)
    keyvals_list = []
    for k, v in autotest_keyvals.items():
      keyvals_list.append('{}={}'.format(k, v))
    keyval_file_content = self._api.file.read_text(
        'Keyval file contents before writing', keyval_file_path,
        'dummyKey=dummyVal')
    self._api.file.write_text(
        'Writing to keyval file', keyval_file_path,
        '{}{}'.format(keyval_file_content, '\n'.join(keyvals_list)), False)
    self._api.file.read_text('Final keyval file contents', keyval_file_path,
                             'dummyKey=dummyVal')
    return True

  def _build_tko_metadata(self, test_results_dir):
    """Construct a phosphorus.Config specific to upload_to_tko step.

    Unlike other steps, upload_to_tko needs to be pointed to the test-specific
    subdirectory of the overall results directory.

    Args:
    * metadata (PhosphorusTestMetadata): Information for one specific test.
    * run_test_response (PhosphorusTestDUTResponse): Response to a test run.

    Returns: phosphorus.Config.

    Raises:
    * InfraFailure.
    """
    tko_metadata = phosphorus.common.Config()
    tko_metadata.task.results_dir = test_results_dir
    tko_metadata.task.test_results_dir = test_results_dir
    tko_metadata.bot.autotest_dir = self.AUTOTEST_PACKAGE_PATH
    return tko_metadata

  def _process_post_process_response(self, response, step):
    """Return the fwinfo from the post_process activity.

    This can be expanded as needed.

    Args:
    * response (api.RunActivitiesResponse): Response from service.

    Returns: (dict): fwinfo map.
    """
    infos = {}
    for resp in response.response.responses:
      if resp.WhichOneof('response') == 'get_fw_info_response':
        info = resp.get_fw_info_response
        infos['ro_fwid'] = info.ro_fwid
        infos['rw_fwid'] = info.rw_fwid
        infos['kernel_version'] = info.kernel_version
        infos['gsc_ro'] = info.gsc_ro
        infos['gsc_rw'] = info.gsc_rw
      elif resp.WhichOneof('response') == 'get_gfx_info_response':
        step.presentation.logs['gfx'] = resp.get_gfx_info_response.gfx_labels
        # TODO (b/267519521): Uncomment the 2 lines below once TH is ready.
        # for k in resp.get_gfx_info_response.gfx_labels:
        #   infos[k] = resp.get_gfx_info_response.gfx_labels[k]
    step.presentation.logs['infos'] = infos

    return infos

  def upload_to_rdb(
      self, metadata, run_test_response, skip_board_model_check=False,
      visibility_mode=TestResultVisibility.TEST_RESULTS_VISIBILITY_UNSPECIFIED,
      custom_realm=''):
    """Uploads test results to resultDB.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test job.
    * run_test_response (DUTTestResponse): The response to the test run.
    * skip_board_model_check (Boolean): Whether to skip verifying board-model realm exists.
    * visibility_mode (TestResultsVisibility): Intended visibility of test results.
    * custom_realm (string): Name of custom realm results should be published to.
    """
    tast_results_dirs = []
    skylab_test_results = []
    missing_test_names = []
    tast_test_exists = False
    with self._api.step.nest('CrosToolRunner: upload to rdb') as presentation:
      test_case_metadata_list = TestCaseMetadataList()
      # Iterate through the test_dut_responses(CrosToolRunnerTestDUTResponse type).
      # Retrieve ctr_test_response(TestCaseResult type).

      with self._api.step.nest('CrosToolRunner: post_proceess') as step:
        # We want this step to fail gracefully if there is an error.
        try:
          key = self.cft_test_request.primary_dut.container_metadata_key
          if key in self.cft_test_request.container_metadata.containers:
            if 'post-process' in self.cft_test_request.container_metadata.containers[
                key].images:
              primary_dut_device = ctr.CrosToolRunnerPostTestRequest.Device(
                  dut=metadata.primary_dut, container_metadata_key=self
                  .cft_test_request.primary_dut.container_metadata_key)

              request = post_request.RunActivitiesRequest(requests=[
                  post_request.Request(
                      get_fw_info_request=post_request.GetFWInfoRequest()),
                  post_request.Request(
                      get_gfx_info_request=post_request.GetGfxInfoRequest())
              ])
              post_process_request = ctr.CrosToolRunnerPostTestRequest(
                  primary_dut=primary_dut_device,
                  artifact_dir=metadata.artifact_dir, request=request,
                  container_metadata_key=self.cft_test_request.primary_dut
                  .container_metadata_key)
              resp = self._api.cros_tool_runner.post_process(
                  post_process_request)
              pp_resp = self._process_post_process_response(resp, step)
              for k, v in pp_resp.items():
                if k and v:
                  metadata.rdb_base_tags.append((k, v))
        except Exception as e:  # pragma: nocover # pylint: disable=broad-except
          step.presentation.status = self._api.step.FAILURE
          step.presentation.logs[
              'failure details'] = f'Exception during FW parsing: {e}'
          step.presentation.logs[
              'full'] = f'Exception during PostProcess parsing: {traceback.format_exc()}'
      for test_dut_response in run_test_response:
        ctr_test_response = test_dut_response.data
        test_harness_type = ctr_test_response.test_harness.WhichOneof(
            'test_harness_type')
        results_dir = ctr_test_response.result_dir_path.path
        test_case_id = ctr_test_response.test_case_id.value
        test_case_metadata = ctr_test_response.test_case_metadata
        if test_case_metadata:
          test_case_metadata_list.values.append(test_case_metadata)

        with self._api.step.nest(test_case_id):
          if test_harness_type == self.TEST_HARNESS_TAST:
            if not tast_test_exists:
              # Append directory path of two level up.
              # Example: results_dir=<base_path>/cros-test/artifact/tast/tests/<test_id>
              # Here 'tast' folder will have the results(streamed_results.jsonl).
              # So we need to append that and only once to cover all tast cases.
              tast_results_dirs.append(
                  str(
                      self._api.path.dirname(
                          self._api.path.dirname(results_dir))))
              tast_test_exists = True
          elif test_harness_type == self.TEST_HARNESS_TAUTO:
            # check if it is tast via tauto.
            tast_folder_path = self._api.path.join(results_dir,
                                                   self.TEST_HARNESS_TAST)
            self._api.path.mock_add_paths(tast_folder_path)
            # if 'tast' folder exists in results_dir, it is tast via tauto.
            if self._api.path.exists(tast_folder_path):
              # for tast_via_tauto case, test results(streamed_results.jsonl) lives inside 'results'.
              tast_results_dirs.append(
                  str(
                      self._api.path.join(tast_folder_path,
                                          self.RESULTS_DIR_NAME)))
              # if any tast cases missing, retrieve them from keyval for later processing.
              missing_test_names.extend(
                  self._get_missing_tast_tests_from_keyval(results_dir))
            else:
              # for tauto, convert result to skylab_test_result.
              skylab_test_results.append(
                  self._convert_ctr_test_result_to_skylab_test_result(
                      ctr_test_response))

      # Serialize TestCaseMetadataList to JSON in order to pass it to the RDB adapter.
      test_case_metadata_json = json_format.MessageToJson(
          test_case_metadata_list)
      presentation.logs['test_case_metadata_list'] = test_case_metadata_json

      # Process tauto tests
      if skylab_test_results:
        skylab_test_runner_result = Skylab_Result(
            autotest_result=Skylab_Result.Autotest(
                test_cases=skylab_test_results))
        temp_dir = self._api.path.mkdtemp()
        autotest_rdb_config = self._autotest_results_rdb_config(
            skylab_test_runner_result,
            temp_dir.join(self.TEST_RUNNER_RESULT_JSON),
            test_case_metadata_json, temp_dir.join(self.TEST_METADATA_JSON),
            metadata, skip_board_model_check, visibility_mode, custom_realm)
        self._api.cros_resultdb.upload(autotest_rdb_config,
                                       str(metadata.testhaus_logs_url))
      # Process tast/tast_via_tauto tests
      for tast_result_dir in tast_results_dirs:
        temp_dir = self._api.path.mkdtemp()
        tast_rdb_config = self._tast_results_rdb_config(
            tast_result_dir, test_case_metadata_json,
            temp_dir.join(self.TEST_METADATA_JSON), metadata,
            skip_board_model_check, visibility_mode, custom_realm)
        self._api.cros_resultdb.upload(tast_rdb_config,
                                       str(metadata.testhaus_logs_url))
      # Process missing tast tests if any
      if missing_test_names:
        self._api.cros_resultdb.report_missing_test_cases(
            missing_test_names, metadata.rdb_base_variant,
            metadata.rdb_base_tags)
      # Apply exonerations
      self._api.cros_resultdb.apply_exonerations(
          [self._api.cros_resultdb.current_invocation_id],
          self.cft_test_request.default_test_execution_behavior)

  def _convert_ctr_test_result_to_skylab_test_result(self, ctr_test_result):
    """Convert provided ctr test result to skylab test result.
    Later this is passed down to result_adapter for tauto test results processing.

    Args:
      ctr_test_result (TestCaseResult): CTR test response for a single test.

    Returns: Skylab_Result.Autotest.TestCase.
    """
    skylab_test_verdict = Skylab_Result.Autotest.TestCase.VERDICT_NO_VERDICT
    ctr_test_verdict = ctr_test_result.WhichOneof('verdict')
    if ctr_test_verdict == 'pass':
      skylab_test_verdict = Skylab_Result.Autotest.TestCase.VERDICT_PASS
    elif ctr_test_verdict in ('fail', 'crash'):
      skylab_test_verdict = Skylab_Result.Autotest.TestCase.VERDICT_FAIL

    start_time = ctr_test_result.start_time.ToSeconds()
    duration = ctr_test_result.duration
    skylab_result = None
    if start_time and duration:
      skylab_result = Skylab_Result.Autotest.TestCase(
          name=ctr_test_result.test_case_id.value, verdict=skylab_test_verdict,
          human_readable_summary=ctr_test_result.reason,
          start_time=timestamp_pb2.Timestamp(seconds=start_time),
          end_time=timestamp_pb2.Timestamp(
              seconds=int(start_time + duration.seconds)))
    else:
      skylab_result = Skylab_Result.Autotest.TestCase(
          name=ctr_test_result.test_case_id.value, verdict=skylab_test_verdict,
          human_readable_summary=ctr_test_result.reason)

    return skylab_result

  def _tast_results_rdb_config(
      self, tast_results_dir, test_metadata_file_content,
      test_metadata_file_path, metadata, skip_board_model_check=False,
      visibility_mode=TestResultVisibility.TEST_RESULTS_VISIBILITY_UNSPECIFIED,
      custom_realm=''):
    """Build rdb config for tast test results.

    Args:
      tast_results_dir (str): path to test results dir.
      test_metadata_file_content (str): CFT test metadata file contents.
      test_metadata_file_path (str): path to the CFT test metadata file.
      metadata (CrosToolRunnerTestMetadata): test metadata for a single test_runner job.
      skip_board_model_check (Boolean): Whether to skip verifying board-model realm exists.
      visibility_mode (TestResultsVisibility): Intended visibility of test results.
      custom_realm (string): Name of custom realm results should be published to.

    Returns: Tast config dict.
    """
    artifact_dir = tast_results_dir.split('/{}/'.format(
        self.ARTIFACT_DIR_NAME))[0]
    artifact_dir = self._api.path.join(artifact_dir, self.ARTIFACT_DIR_NAME)
    config = {
        'result_format':
            'tast',
        'base_variant':
            metadata.rdb_base_variant,
        'base_tags':
            metadata.rdb_base_tags,
        'sources_file':
            metadata.rdb_sources_file,
        'result_file':
            self._api.path.join(tast_results_dir, self.STREAMED_RESULTS_JSON),
        'artifact_directory':
            artifact_dir,
        'skip_board_model_check':
            skip_board_model_check,
        'visibility_mode':
            visibility_mode,
        'custom_realm':
            custom_realm
    }

    if test_metadata_file_content:
      self._api.file.write_text('write tast CFT test metadata',
                                test_metadata_file_path,
                                test_metadata_file_content)
      config['test_metadata_file'] = test_metadata_file_path

    return config

  def _autotest_results_rdb_config(
      self, test_runner_result, test_runner_result_file_path,
      test_metadata_file_content, test_metadata_file_path, metadata,
      skip_board_model_check=False,
      visibility_mode=TestResultVisibility.TEST_RESULTS_VISIBILITY_UNSPECIFIED,
      custom_realm=''):
    """Build rdb config for tauto test results.

    Args:
      test_runner_result (Skylab_Result): skylab test runner results.
      test_runner_result_file_path (str): path to test runner results file.
      test_metadata_file_content (str): CFT test metadata file contents.
      test_metadata_file_path (str): path to the CFT test metadata file.
      metadata (CrosToolRunnerTestMetadata): test metadata for a single test_runner job.
      skip_board_model_check (Boolean): Whether to skip verifying board-model realm exists.
      visibility_mode (TestResultsVisibility): Intended visibility of test results.
      custom_realm (string): Name of custom realm results should be published to.

    Returns: Tauto config dict.
    """
    self._api.file.write_proto('write skylab_test_runner result',
                               test_runner_result_file_path, test_runner_result,
                               'JSONPB')
    config = {
        'result_format': 'skylab-test-runner',
        'base_variant': metadata.rdb_base_variant,
        'base_tags': metadata.rdb_base_tags,
        'sources_file': metadata.rdb_sources_file,
        'result_file': test_runner_result_file_path,
        'artifact_directory': None,
        'skip_board_model_check': skip_board_model_check,
        'visibility_mode': visibility_mode,
        'custom_realm': custom_realm
    }

    if test_metadata_file_content:
      self._api.file.write_text('write skylab_test_runner CFT test metadata',
                                test_metadata_file_path,
                                test_metadata_file_content)
      config['test_metadata_file'] = test_metadata_file_path

    return config

  def _get_missing_tast_tests_from_keyval(self, base_dir):
    """Get missing tast test names from keyval.

    Args:
      base_dir (string): The path to test results.

    Returns: List of missing tast test names.
    """

    keyval_file_path = self._api.path.join(base_dir, self.KEYVAL_FILENAME)
    try:
      content = self._api.file.read_text(
          'read keyval file', keyval_file_path,
          test_data='dummyKey=dummyVal').splitlines()
    except self._api.file.Error:
      content = []
    missing_tests = []
    for line in content:
      if line.startswith(self.TAST_MISSING_TEST_KEY):
        test = self.TAST_TEST_NAME_PREFIX + line.split('=')[-1]
        missing_tests.append(test)

    return missing_tests

  def upload_to_google_storage(self, metadata):
    """Uploads test information to Google Storage for current test.

    Args:
      metadata (DUTTestMetadata): Input information relevant to one test.
    """
    with self._api.step.nest('CrosToolRunner: Phosphorus: upload to GS'):
      self._api.phosphorus.upload_to_gs(
          phosphorus.upload_to_gs.UploadToGSRequest(
              config=None, local_directory=metadata.artifact_dir,
              gs_directory=metadata.gs_url))

  def parse_test_results(self, metadata):
    """For one specific test or group of tests with same configs, get the test results in the form of DUTResult.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test or group of tests with same configs.

    Returns:
      dut_results.DUTResult: Constructed DUTResult for test(s).

    Raises:
    * InfraFailure.
    """
    del metadata

    return CrosToolRunnerResult()

  def logs_gs_url(self):
    """Google storage url for storing logs.

    Returns:
      str: Formatted GS url for logs.
    """
    gs_root = self._properties.config.output.log_data_gs_root
    now = self._api.time.utcnow()
    return '%s/%s/%s' % (gs_root, now.date().isoformat(),
                         self._api.uuid.random())

  def build_test_metadata(self, test_id, test, autotest_keyvals,
                          cft_test_request):
    """Get the test metadata for the designated single set of test(s) for this interface.

    Args:
    * test_id (str): The id for the current test.
    * test (skylab_test_runner.Request.Test): The actual test request for the
    current test.
    * autotest_keyvals (dict): Autotest keyvals map.

    Returns:
      DUTTestMetadata: Compact metadata representing a set of test(s) for this
      interface.
    """
    artifact_dir = str(self._api.path.mkdtemp(self.ARTIFACT_DIR_PREFIX))
    return CrosToolRunnerTestMetadata(
        interface=self, test_id=test_id, test=test,
        cft_test_request=cft_test_request, autotest_keyvals=autotest_keyvals,
        artifact_dir=artifact_dir, image_storage_server=None,
        invocation_id=self._api.cros_resultdb.current_invocation_id)

  def get_results_directory(self, metadata):
    """Retrieves the directory whereupon results are deposited.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      str
    """
    return metadata.artifact_dir

  def is_within_deadline(self):
    """Determines if a test is within deadline.

    If the properties have a deadline, and it is exceded set the step to
    failed and return False, else return True.

    Returns:
      bool: False for exceeded, True for not.
    """
    with self._api.step.nest('DUTInterface: check request deadline') as step:
      if self._properties.cft_test_request.HasField('deadline'):
        deadline = self._properties.cft_test_request.deadline
        current_time = self._api.time.time()
        if deadline.seconds < current_time:
          step.presentation.status = self._api.step.FAILURE
          return False
    return True

  @staticmethod
  def build_empty_result():
    """Get a DUT result without items in it (useful for building).

    Returns:
      dut_results.DUTResult
    """
    return CrosToolRunnerResult()

  @staticmethod
  def build_aborted_prejob_response(test_metadata):
    """Get a prejob response representation for an aborted job.

    Args:
    * test_metadata (DUTTestMetadata):  Input information relevant to one test. (Not used)

    Returns:
      PrejobResponsesTuple
    """
    del test_metadata

    return PrejobResponsesTuple(
        [CrosToolRunnerPrejobDUTResponse.build_aborted_response('dut')], True,
        'REASON_PROVISIONING_FAILED')

  def process_test_responses(self, cros_test_responses):
    """Process test responses from run_test.

    Args:
    * cros_test_responses (TestResponse):  Test responses from run_test.

    Returns:
      processed test responses tuple: (test_responses_for_output_props, test_response_for_result_uploading)
    """
    with self._api.step.nest('Processing CTR Test Responses') as step:
      ret1_ids = []
      ret2_ids = []

      path_to_tauto_dut_resp_dict = defaultdict(list)
      path_to_tast_dut_resp_dict = defaultdict(list)

      for test_dut_response in cros_test_responses.test_dut_responses:
        ctr_test_response = test_dut_response.data
        test_harness_type = ctr_test_response.test_harness.WhichOneof(
            'test_harness_type')
        results_dir = ctr_test_response.result_dir_path.path
        #test_case_id = ctr_test_response.test_case_id.value
        if test_harness_type == CrosToolRunnerInterface.TEST_HARNESS_TAUTO:
          path_to_tauto_dut_resp_dict[results_dir].append(test_dut_response)
        elif test_harness_type == CrosToolRunnerInterface.TEST_HARNESS_TAST:
          path_to_tast_dut_resp_dict[results_dir].append(test_dut_response)

      tast_via_tauto = False
      # Independent Tauto and Tast tests. [For reporting back to CTP/CQ via output props]
      ret1 = []
      # All tauto (independent tauto and tast via tauto) and tast tests. [For result uploading]
      ret2 = []

      # Identify if tast_via_tauto exists and start constructing new response.
      for path, resp_list in path_to_tauto_dut_resp_dict.items():
        if path in path_to_tast_dut_resp_dict:
          # This means we have tast via tauto test case(s).
          tast_via_tauto = True

        for resp in resp_list:
          ret2.append(resp)
          ret2_ids.append(resp.data.test_case_id.value)
          if path not in path_to_tast_dut_resp_dict:
            ret1.append(resp)
            ret1_ids.append(resp.data.test_case_id.value)

      if not tast_via_tauto:
        # If no tast_via_tauto in test cases, keep the responses as is.
        step.presentation.logs[
            'Output'] = 'No tast_via_tauto found. So no processing required.'
        return cros_test_responses, cros_test_responses

      for path, resp_list in path_to_tast_dut_resp_dict.items():
        for resp in resp_list:
          ret1.append(resp)
          ret1_ids.append(resp.data.test_case_id.value)
          if path not in path_to_tauto_dut_resp_dict:
            # If not tast_via_tauto, add this independant tast result to response.
            ret2.append(resp)
            ret2_ids.append(resp.data.test_case_id.value)

      step.presentation.logs['For_Output_Props_Test_Ids'] = ret1_ids
      step.presentation.logs['For_Result_Uploading_Test_Ids'] = ret2_ids

      return RunTestResponsesTuple(
          ret1, cros_test_responses.any_test_failed), RunTestResponsesTuple(
              ret2, cros_test_responses.any_test_failed)

  @staticmethod
  def _read_dut_hostname(api):
    """Retrieve the DUT hostname dynamically.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API.

    Returns:
      str
    """
    return api.phosphorus.read_dut_hostname()

  @staticmethod
  def _get_updated_keyvals(metadata):
    """Gets the keyval from autotest and populates it with the latest URLs.

    This keyval is required for stainless' test results view to link to the
    test logs.
    - Autoserv drops keyvals in a file in the logs directory
    - tko/parse parses that file and injects keyvals in the TKO database
    - Stainless table builder extracts this particular keyval and uses the value
      to link to the archived logs.

    Args:
    * metadata (CrosToolRunnerTestMetadata): Input information relevant test(s) in CTR.

    Returns:
      dict: The updated keyvals.
    """
    keyvals = metadata.autotest_keyvals
    keyvals['synchronous_log_data_url'] = metadata.gs_url
    keyvals['synchronous_log_data_stainless_url'] = metadata.stainless_logs_url
    keyvals['synchronous_log_data_testhaus_url'] = metadata.testhaus_logs_url
    if metadata.job_finished:
      keyvals['job_finished'] = str(metadata.job_finished)
    return keyvals

  def _process_prejob_response(self, prejob_resp):
    """Process prejob responses received from cros_tool_runner.
    The response can have multiple provisioning results.
    Process each of one of them and create PrejobResponsesTuple.

    Args:
    * prejob_resp (CrosToolRunnerProvisionResponse): Provision response.

    Returns:
      PrejobResponsesTuple
    """
    prejob_dut_responses = []
    any_provision_failed = False
    failure_reason = ''
    for each_resp in prejob_resp.responses:
      prejob_dut_resp = CrosToolRunnerPrejobDUTResponse(each_resp.id.value,
                                                        each_resp)
      prejob_dut_responses.append(prejob_dut_resp)
      if prejob_dut_resp.is_failure():
        any_provision_failed = True
        if each_resp.failure and each_resp.failure.reason:
          failure_reason = ctr_api.provision_service.InstallFailure.Reason.Name(
              each_resp.failure.reason)
    return PrejobResponsesTuple(prejob_dut_responses, any_provision_failed,
                                failure_reason)

  def _process_run_test_response(self, runtest_resp):
    """Process run_test responses received from cros_tool_runner.
    The response can have multiple test execution results.
    Process each of one of them and create RunTestResponsesTuple.

    Args:
    * runtest_resp (CrosToolRunnerTestResponse): Provision response.

    Returns:
      RunTestResponsesTuple
    """
    test_dut_responses = []
    any_test_failed = False
    for each_resp in runtest_resp.test_case_results:
      test_dut_resp = CrosToolRunnerTestDUTResponse(
          each_resp.test_case_id.value, each_resp)
      test_dut_responses.append(test_dut_resp)
      if test_dut_resp.is_failure():
        any_test_failed = True
    return RunTestResponsesTuple(test_dut_responses, any_test_failed)

  def should_update_os_bundled_firmware(self, device):
    fw_config = self._properties.common_config.cros_firmware_update_config
    if not fw_config.enabled:
      return False
    # If there is specific firmware requested, then we should skip update
    # os bundled firmware as the DUT's firmware will be updated to the
    # specified version during firmware provisioning.
    if (device.provision_state.firmware.main_rw_payload.firmware_image_path.path
        or
        device.provision_state.firmware.main_ro_payload.firmware_image_path.path
       ):
      return False

    # Get all of the pools that this DUT belongs to
    label_pool = self._api.cros_tags.get_values(
        'label-pool', self._api.buildbucket.swarming_bot_dimensions)

    # Check to see if this dut is in a pool that also prevents firmware updates
    if label_pool and 'mp_firmware_testing' in label_pool:
      return False

    # There will be only one of list(allow/block) at a given time, so the order
    # of below blocks doesn't matters.
    if fw_config.HasField('allow_list'):
      return (device.dut_model.build_target in fw_config.allow_list.boards or
              device.dut_model.model_name in fw_config.allow_list.models)
    if fw_config.HasField('block_list'):
      return (device.dut_model.build_target not in fw_config.block_list.boards
              and
              device.dut_model.model_name not in fw_config.block_list.models)
    # We shouldn't hit here ever, but for safe we return False if it happens.
    return False

  def get_test_execution_metadata(self):
    """Checks the first test case harness type and creates test execution
    metadata based on it.

    Returns:
      Anypb: test execution metadata packed inside.
    """
    metadata_anypb = None
    test_execution_metadata = None
    if len(self.cft_test_request.test_suites) == 0:
      return metadata_anypb

    first_test = self.cft_test_request.test_suites[
        0].test_case_ids.test_case_ids[0].value
    gcs_path = self.cft_test_request.primary_dut.provision_state.system_image.system_image_path.path
    if gcs_path:
      if not gcs_path.endswith('/'):
        gcs_path = gcs_path + '/'
      if first_test.startswith('tast'):
        arg = Test_Execution_Metadata.Arg(flag='buildartifactsurl',
                                          value=gcs_path)
        test_execution_metadata = Test_Execution_Metadata.TastExecutionMetadata(
            args=[arg])
      elif first_test.startswith('tauto'):
        tauto_arg = Test_Execution_Metadata.AutotestExecutionMetadata.Arg(
            flag='buildartifactsurl', value=gcs_path)
        test_execution_metadata = Test_Execution_Metadata.AutotestExecutionMetadata(
            args=[tauto_arg])

    if test_execution_metadata:
      metadata_anypb = Any()
      metadata_anypb.Pack(test_execution_metadata)

    return metadata_anypb
