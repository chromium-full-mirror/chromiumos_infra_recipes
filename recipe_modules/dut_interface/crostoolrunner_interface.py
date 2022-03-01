# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple

from .crostoolrunner_results import CrosToolRunnerResult, CrosToolRunnerPrejobDUTResponse, CrosToolRunnerTestDUTResponse

from . import dut_interface

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.chromiumos.test.lab.api.dut import Dut
from PB.chromiumos.test.lab.api.dut import CacheServer
from PB.chromiumos.test.lab.api.ip_endpoint import IpEndpoint

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

  def __init__(self, interface, test_id, test, image_storage_server=''):
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

    # TODO(b/220801059): Once DutToplogy is rolled out and inventory service is implemented,
    # fetch dut topology from inventory service instead of phosphorus.
    self.load_response = interface.load_skylab_local_state(
        test=test, test_id=test_id)
    self.primary_dut = self.load_response.dut_topology[0]
    # TODO(b/220801220): Match peer_duts appropriately when multi-dut testing feature is enabled for CFT.
    self.peer_duts = []
    self.default_cache_server_address = "100.115.220.100"
    self.default_cache_server_port = 8082
    self.output_dir = "output_dir"


class CrosToolRunnerInterface(dut_interface.DUTInterface):  # pragma: no cover

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
    dut_details = Dut.ChromeOS(
        ssh=IpEndpoint(address=metadata.primary_dut.hostname, port=0),
        dut_model=self.cft_mvp_request.primary_dut.dut_model)
    cache_server_info = CacheServer(
        address=IpEndpoint(address=metadata.default_cache_server_address,
                           port=metadata.default_cache_server_port))
    primary_dut = Dut(
        id=Dut.Id(value=metadata.primary_dut.hostname), chromeos=dut_details,
        cache_server=cache_server_info)
    with self._api.step.nest('CrosToolRunner: run provision'):
      with self._api.context(infra_steps=True):
        provision_request = ctr.CrosToolRunnerProvisionRequest(devices=[
            ctr.CrosToolRunnerProvisionRequest.Device(
                dut=primary_dut, provision_state=self.cft_mvp_request
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
      dut_details = Dut.ChromeOS(
          ssh=IpEndpoint(address=metadata.primary_dut.hostname, port=0),
          dut_model=self.cft_mvp_request.primary_dut.dut_model)
      cache_server_info = CacheServer(
          address=IpEndpoint(address=metadata.default_cache_server_address,
                             port=metadata.default_cache_server_port))
      primary_dut = Dut(
          id=Dut.Id(value=metadata.primary_dut.hostname), chromeos=dut_details,
          cache_server=cache_server_info)
      primary_dut_device = ctr.CrosToolRunnerTestRequest.Device(
          dut=primary_dut, container_metadata_key=self.cft_mvp_request
          .primary_dut.container_metadata_key)
      run_test_request = ctr.CrosToolRunnerTestRequest(
          test_suites=self.cft_mvp_request.test_suites,
          primary_dut=primary_dut_device, artifact_dir=metadata.output_dir)
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
      # New Dut Topology will be enabled once it is rolled out.
      with self._api.context(env={'USE_DUT_TOPO': False}):
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
          dut_state=dut_state, dut_name=metadata.primary_dut.hostname,
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
          dut_state=dut_state, dut_name=metadata.primary_dut.hostname,
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
    raise NotImplementedError

  def upload_to_google_storage(self, metadata):
    """Uploads test information to Google Storage for current test.

    Args:
      metadata (DUTTestMetadata): Input information relevant to one test.
    """
    raise NotImplementedError

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

  def build_test_metadata(self, test_id, test):
    """Get the test metadata for the designated single set of test(s) for this interface.

    Args:
    * test_id (str): The id for the current test.
    * test (skylab_test_runner.Request.Test): The actual test request for the
    current test.

    Returns:
      DUTTestMetadata: Compact metadata representing a set of test(s) for this
      interface.
    """
    return CrosToolRunnerTestMetadata(self, test_id, test, None)

  def get_results_directory(self, metadata):
    """Retrieves the directory whereupon results are deposited.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      str
    """
    return metadata.output_dir

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
