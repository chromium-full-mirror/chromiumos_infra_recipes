# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple

from .crostoolrunner_results import CrosToolRunnerResult, CrosToolRunnerPrejobDUTResponse, CrosToolRunnerTestDUTResponse

from . import dut_interface

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.test_platform import phosphorus

RunTestResponsesTuple = namedtuple('RunTestResponsesTuple',
                                   ['test_dut_responses'])
PrejobResponsesTuple = namedtuple(
    'PrejobResponsesTuple', ['prejob_dut_responses', 'any_provision_failed'])


class CrosToolRunnerTestMetadata(dut_interface.DUTTestMetadata
                                ):  # pragma: no cover
  """
  Holds metadata specific to one test or a group of tests.
  Passable to DutInterface that requires info from this class to provision, run tests etc.
  """
  DUT_HOSTNAME_SUFFIX = 'cros'

  def __init__(self, interface, test_id, test, autotest_keyvals=None,
               artifact_dir='', image_storage_server=''):
    """Specific constructor for CrosToolRunner subclass of DUTTestMetadata

    Args:
    * interface (CrosToolRunnerInterface):
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    * image_storage_server (str): Image storage server info.
    """
    super(CrosToolRunnerTestMetadata,
          self).__init__(test_id=test_id, test=test,
                         gs_url=interface.logs_gs_url(),
                         image_storage_server=image_storage_server)

    self.artifact_dir = artifact_dir
    self.autotest_keyvals = autotest_keyvals
    self.load_response = interface.load_skylab_local_state(
        test=test, test_id=test_id)
    # Each topology can have multiple duts info for multi-dut testing scenario.
    # But there should be always one lab_dut_topology as we load one dut info at a time.
    # TODO(b/220801220): When multi-dut testing is enabled for CFT, make sure first dut is always primary dut.
    self.primary_dut = self.load_response.lab_dut_topology[0].duts[0]
    # CTR expects hostname.cros format for ssh endpoint address
    self.primary_dut.chromeos.ssh.address = '{}.{}'.format(
        self.primary_dut.chromeos.ssh.address, self.DUT_HOSTNAME_SUFFIX)
    # TODO(b/220801220): Match peer_duts appropriately when multi-dut testing feature is enabled for CFT.
    self.peer_duts = []

class CrosToolRunnerInterface(dut_interface.DUTInterface):  # pragma: no cover

  ARTIFACT_DIR_PREFIX = 'output_dir'
  KEYVAL_FILENAME = 'keyval'
  TEST_HARNESS_TAUTO = 'tauto'
  TEST_HARNESS_TAST = 'tast'
  AUTOTEST_PACKAGE_PATH = '/usr/local/autotest'

  def __init__(self, api, properties):
    """DUTInterface implementation with cros-tool-runner.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API.
    * properties (TestRunnerProperties): Input properties to the recipe.
    """
    super(CrosToolRunnerInterface, self).__init__(api, properties)
    self.cft_mvp_request = self._properties.cft_mvp_test_request

  def submit_pre_job(self, metadata, max_duration_seconds=0):
    """Submits a Prejob execution on the DUT.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * max_duration_seconds (int): The longest amount of time this test may run. (Not used)

    Returns:
      PrejobResponsesTuple: The prejob responses in ['prejob_dut_responses', 'any_provision_failed'] tuple.

    Raises:
      * api.test.StepFailure If prejob fails.
    """
    with self._api.step.nest('CrosToolRunner: run provision'):
      with self._api.context(infra_steps=True):
        provision_request = ctr.CrosToolRunnerProvisionRequest(devices=[
            ctr.CrosToolRunnerProvisionRequest.Device(
                dut=metadata.primary_dut, provision_state=self.cft_mvp_request
                .primary_dut.provision_state, container_metadata_key=self
                .cft_mvp_request.primary_dut.container_metadata_key)
        ])
        return self._process_prejob_response(
            self._api.cros_tool_runner.provision(provision_request))

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
    with self._api.step.nest('CrosToolRunner: run test'):
      primary_dut_device = ctr.CrosToolRunnerTestRequest.Device(
          dut=metadata.primary_dut, container_metadata_key=self.cft_mvp_request
          .primary_dut.container_metadata_key)
      run_test_request = ctr.CrosToolRunnerTestRequest(
          test_suites=self.cft_mvp_request.test_suites,
          primary_dut=primary_dut_device, artifact_dir=metadata.artifact_dir)
      return self._process_run_test_response(
          self._api.cros_tool_runner.test(run_test_request))

  def load_skylab_local_state(
      self, test=None, test_id=dut_interface.DUTTestMetadata.DUMMY_TEST_ID):
    """Get skylab local state from DUT for specific test(s).

    Args:
    * test (skylab_test_runner.Request.Test): The actual test request. (Not used)
    * test_id (str): The desired test to pull state from. (Not required)

    Returns:
      skylab_local_state.LoadResponse
    """
    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: load skylab local state'):
      with self._api.context(env={'USE_DUT_TOPO': True}):
        return self._api.phosphorus.load_skylab_local_state(test_id=test_id)

  def save_skylab_local_state(self, dut_state, metadata):
    """Save skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: mark local DUT state: {}'.format(
            dut_state)):
      self._api.phosphorus.save_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.id.value,
          peer_duts=[dut.hostname for dut in metadata.peer_duts])

  def save_and_seal_skylab_local_state(self, dut_state, metadata):
    """Save and seal skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    with self._api.step.nest(
        'CrosToolRunner: Phosphorus: save local DUT state'):
      self._api.phosphorus.save_and_seal_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.id.value,
          peer_duts=[dut.hostname for dut in metadata.peer_duts])

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
    * run_test_response (DUTTestResponse): The response to the test run.

    Raises:
    * InfraFailure.
    """
    all_valid_result_dir = True
    with self._api.step.nest('CrosToolRunner: Phosphorus: upload to TKO'):
      # Iterate through the test_dut_responses(CrosToolRunnerTestDUTResponse type).
      # Retrieve ctr_test_response(TestCaseResult type) and check which test cases are of harness type 'tauto'.
      # For 'tauto' harness type, try to upload test results to TKO.
      for test_dut_response in run_test_response.test_dut_responses:
        ctr_test_response = test_dut_response.data
        test_harness_type = ctr_test_response.test_harness.WhichOneof(
            'test_harness_type')
        results_dir = ctr_test_response.result_dir_path.path
        test_case_id = ctr_test_response.test_case_id.value
        with self._api.step.nest(test_case_id) as step:
          if test_harness_type == self.TEST_HARNESS_TAUTO:
            if self._write_to_keyvals(results_dir,
                                      self._with_gs_logs_keyval(metadata)):
              with self._api.context(infra_steps=True):
                self._api.phosphorus.upload_to_tko(
                    phosphorus.upload_to_tko.UploadToTkoRequest(
                        config=self._build_tko_metadata(results_dir)))
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

  def build_test_metadata(self, test_id, test, autotest_keyvals):
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
    return CrosToolRunnerTestMetadata(interface=self, test_id=test_id,
                                      test=test,
                                      autotest_keyvals=autotest_keyvals,
                                      artifact_dir=artifact_dir,
                                      image_storage_server=None)

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
      if self._properties.cft_mvp_test_request.HasField('deadline'):
        deadline = self._properties.cft_mvp_test_request.deadline
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
    return PrejobResponsesTuple(
        [CrosToolRunnerPrejobDUTResponse.build_aborted_response('dut')], True)

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
  def _with_gs_logs_keyval(metadata):
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
    for each_resp in prejob_resp.responses:
      prejob_dut_resp = CrosToolRunnerPrejobDUTResponse(each_resp.id.value,
                                                        each_resp)
      prejob_dut_responses.append(prejob_dut_resp)
      if prejob_dut_resp.is_failure():
        any_provision_failed = True
    return PrejobResponsesTuple(prejob_dut_responses, any_provision_failed)

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
    for each_resp in runtest_resp.test_case_results:
      test_dut_resp = CrosToolRunnerTestDUTResponse(
          each_resp.test_case_id.value, each_resp)
      test_dut_responses.append(test_dut_resp)
    return RunTestResponsesTuple(test_dut_responses)
