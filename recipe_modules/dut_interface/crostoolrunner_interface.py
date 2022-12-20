# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
from collections import defaultdict
from google.protobuf import timestamp_pb2

from RECIPE_MODULES.chromeos.dut_interface.crostoolrunner_results import CrosToolRunnerResult, CrosToolRunnerPrejobDUTResponse, CrosToolRunnerTestDUTResponse

from RECIPE_MODULES.chromeos.dut_interface import dut_interface

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.chromiumos.test.lab import api as lab_api
from PB.test_platform import phosphorus
from PB.test_platform.skylab_local_state.load import Dut as LoadDut
from PB.test_platform.skylab_local_state.load import LoadResponse
from PB.test_platform.skylab_test_runner.result import Result as Skylab_Result

RunTestResponsesTuple = namedtuple('RunTestResponsesTuple',
                                   ['test_dut_responses', 'any_test_failed'])
PrejobResponsesTuple = namedtuple(
    'PrejobResponsesTuple', ['prejob_dut_responses', 'any_provision_failed'])




class CrosToolRunnerTestMetadata(dut_interface.DUTTestMetadata
                                ):  # pragma: no cover
  """
  Holds metadata specific to one test or a group of tests.
  Passable to DutInterface that requires info from this class to provision, run tests etc.
  """

  def __init__(self, interface, test_id, test, autotest_keyvals=None,
               artifact_dir='', image_storage_server=''):
    """Specific constructor for CrosToolRunner subclass of DUTTestMetadata

    Args:
    * interface (CrosToolRunnerInterface):
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    * image_storage_server (str): Image storage server info.
    """
    super().__init__(test_id=test_id, test=test, gs_url=interface.logs_gs_url(),
                     image_storage_server=image_storage_server)

    self.artifact_dir = artifact_dir
    self.autotest_keyvals = autotest_keyvals
    self.load_response = interface.load_skylab_local_state(
        test=test, test_id=test_id)
    # Each topology can have multiple duts info for multi-dut testing scenario.
    # But there should be always one lab_dut_topology as we load one dut info at a time.
    # TODO(b/220801220): When multi-dut testing is enabled for CFT, make sure first dut is always primary dut.
    self.primary_dut = self.load_response.lab_dut_topology[0].duts[0]
    # TODO(b/220801220): Match peer_duts appropriately when multi-dut testing feature is enabled for CFT.
    self.peer_duts = []
    # Unix time of when test execution finished. Used to be passed via keyvals for autotests.
    self.job_finished = 0
    # Info used in rdb upload.
    self.rdb_base_tags = None
    self.rdb_base_variant = None


class CrosToolRunnerInterface(dut_interface.DUTInterface):  # pragma: no cover

  ARTIFACT_DIR_PREFIX = 'output_dir'
  KEYVAL_FILENAME = 'keyval'
  TEST_HARNESS_TAUTO = 'tauto'
  TEST_HARNESS_TAST = 'tast'
  AUTOTEST_PACKAGE_PATH = '/usr/local/autotest'
  TAST_MISSING_TEST_KEY = 'tast_missing_test'
  RESULTS_DIR_NAME = 'results'
  ARTIFACT_DIR_NAME = 'artifact'
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
                      value="fake_dut"), cache_server=lab_api.dut.CacheServer(
                          address=lab_api.ip_endpoint.IpEndpoint(
                              address="0.0.0.0", port=8080)),
                  chromeos=lab_api.dut.Dut.ChromeOS(
                      dut_model=lab_api.dut.DutModel(
                          build_target="betty", model_name="betty"), ssh=lab_api
                      .ip_endpoint.IpEndpoint(address="fake_host", port=22)))
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
    check_suite = 'cheets_CTS_R' in self.cft_test_request.test_suites[
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
    project = 'betty-cloud-prototype'
    self._api.gcloud.set_gce_project(project=project)
    self._api.gcloud.auth_list()

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
    gce_image = 'ctstest-{}-{}-{}'.format(
        # bot name
        bot_name,
        # Drop betty-arc-r-release/ to save some length since image name length
        # is capped at 63 characters.
        '-'.join(build.split('/')[1:]).lower()[0:10],
        # buildbucket id
        suffix)

    source_uri = 'https://storage.googleapis.com/chromeos-image-archive/{}/chromiumos_test_image_gce.tar.gz'.format(
        build)

    self._vm_provisioned = {}

    with self._api.step.nest('clean up orphan instances'):
      for orphance_instance in self._api.gcloud.list_all_instances():
        if orphance_instance.startswith('ctstest-{}-'.format(bot_name)):
          # recipe_modules/gcloud uses the same name for instances and images.
          self._api.gcloud.delete_instance(orphance_instance, project,
                                           'us-west2-a')
          self._api.gcloud.delete_image(orphance_instance)

    self._api.gcloud.create_image(
        gce_image, source_uri=source_uri, licenses=[
            'https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx',
        ])
    self._vm_provisioned['image_name'] = gce_image

    instance_name, _, extip = self._api.gcloud.create_instance(
        gce_image, project, 'n2-standard-4', 'us-west2-a', 'default', 'default',
        external_ip=True)
    self._vm_provisioned['instance_name'] = instance_name

    self._api.step('wait for betty boots', [
        '/usr/bin/ssh', '-o', 'StrictHostKeyChecking=no', '-o',
        'UserKnownHostsFile=/dev/null', '-o', 'BatchMode=yes', 'root@' + extip,
        'true'
    ])

    metadata.primary_dut.chromeos.ssh.address = extip

    return PrejobResponsesTuple([], False)

  def _vm_shutdown_and_cleanup(self):
    """Shutsdown and cleanup environment on GCE."""

    if not self._vm_provisioned:
      return

    project = 'betty-cloud-prototype'

    if 'instance_name' in self._vm_provisioned:
      self._api.gcloud.delete_instance(self._vm_provisioned['instance_name'],
                                       project, 'us-west2-a')

    if 'image_name' in self._vm_provisioned:
      self._api.gcloud.delete_image(self._vm_provisioned['image_name'])

  def submit_post_job(self):
    """Submits a Postjob for VM"""

    if not self._vm_is_vmtest():
      return

    with self._api.step.nest('Prototype GCE shutdown'):
      self._vm_shutdown_and_cleanup()

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
    del max_duration_seconds

    if self._vm_is_vmtest():
      with self._api.step.nest('Prototype GCE provision') as step:
        return self._vm_direct_provision(metadata)

    with self._api.step.nest('CrosToolRunner: run provision') as step:
      with self._api.context(infra_steps=True):
        self.cft_test_request.primary_dut.provision_state.update_firmware = \
          self.should_update_os_bundled_firmware(self.cft_test_request.primary_dut)
        provision_request = ctr.CrosToolRunnerProvisionRequest(devices=[
            ctr.CrosToolRunnerProvisionRequest.Device(
                dut=metadata.primary_dut, provision_state=self.cft_test_request
                .primary_dut.provision_state, container_metadata_key=self
                .cft_test_request.primary_dut.container_metadata_key)
        ])
        prejob_response = self._process_prejob_response(
            self._api.cros_tool_runner.provision(provision_request))

        if prejob_response.any_provision_failed:
          step.presentation.status = self._api.step.FAILURE

        return prejob_response

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
      run_test_request = ctr.CrosToolRunnerTestRequest(
          test_suites=self.cft_test_request.test_suites,
          primary_dut=primary_dut_device, artifact_dir=metadata.artifact_dir)
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

  def save_skylab_local_state(self, dut_state, metadata):
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
          peer_duts=[dut.hostname for dut in metadata.peer_duts])

  def save_and_seal_skylab_local_state(self, dut_state, metadata):
    """Save and seal skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    if self._vm_is_vmtest():
      self._api.step('stub save local DUT state', ['echo', dut_state])
      return

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

  def upload_to_rdb(self, metadata, run_test_response,
                    force_current_realm=False):
    """Uploads test results to resultDB.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test job.
    * run_test_response (DUTTestResponse): The response to the test run.
    * force_current_realm (Boolean): Whether to force publishing to rdb in the current realm
    """
    tast_results_dirs = []
    skylab_test_results = []
    missing_test_names = []
    tast_test_exists = False
    with self._api.step.nest('CrosToolRunner: upload to rdb'):
      # Iterate through the test_dut_responses(CrosToolRunnerTestDUTResponse type).
      # Retrieve ctr_test_response(TestCaseResult type).
      for test_dut_response in run_test_response:
        ctr_test_response = test_dut_response.data
        test_harness_type = ctr_test_response.test_harness.WhichOneof(
            'test_harness_type')
        results_dir = ctr_test_response.result_dir_path.path
        test_case_id = ctr_test_response.test_case_id.value
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

      # Process tauto tests
      if skylab_test_results:
        skylab_test_runner_result = Skylab_Result(
            autotest_result=Skylab_Result.Autotest(
                test_cases=skylab_test_results))
        autotest_rdb_config = self._autotest_results_rdb_config(
            skylab_test_runner_result,
            (self._api.path.mkdtemp()).join(self.TEST_RUNNER_RESULT_JSON),
            metadata, force_current_realm)
        self._api.cros_resultdb.upload(autotest_rdb_config,
                                       str(metadata.stainless_logs_url))
      # Process tast/tast_via_tauto tests
      for tast_result_dir in tast_results_dirs:
        tast_rdb_config = self._tast_results_rdb_config(tast_result_dir,
                                                        metadata,
                                                        force_current_realm)
        self._api.cros_resultdb.upload(tast_rdb_config,
                                       str(metadata.stainless_logs_url))
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
    elif ctr_test_verdict == 'fail':
      skylab_test_verdict = Skylab_Result.Autotest.TestCase.VERDICT_FAIL

    start_time = ctr_test_result.start_time.ToSeconds()
    duration = ctr_test_result.duration
    skylab_result = None
    if start_time and duration:
      skylab_result = Skylab_Result.Autotest.TestCase(
          name=ctr_test_result.test_case_id.value, verdict=skylab_test_verdict,
          human_readable_summary=ctr_test_result.reason,
          start_time=timestamp_pb2.Timestamp(seconds=start_time),
          end_time=timestamp_pb2.Timestamp(start_time + duration.seconds))
    else:
      skylab_result = Skylab_Result.Autotest.TestCase(
          name=ctr_test_result.test_case_id.value, verdict=skylab_test_verdict,
          human_readable_summary=ctr_test_result.reason)

    return skylab_result

  def _tast_results_rdb_config(self, tast_results_dir, metadata,
                               force_current_realm=False):
    """Build rdb config for tast test results.

    Args:
      tast_results_dir (str): path to test results dir.
      metadata (CrosToolRunnerTestMetadata): test metadata for a single test_runner job.

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
        'result_file':
            self._api.path.join(tast_results_dir, self.STREAMED_RESULTS_JSON),
        'artifact_directory':
            artifact_dir,
        'force_current_realm':
            force_current_realm
    }
    return config

  def _autotest_results_rdb_config(self, test_runner_result,
                                   test_runner_result_file_path, metadata,
                                   force_current_realm=False):
    """Build rdb config for tauto test results.

    Args:
      test_runner_result (Skylab_Result): skylab test runner results.
      test_runner_result_file_path (str): path to test runner results file.
      metadata (CrosToolRunnerTestMetadata): test metadata for a single test_runner job.

    Returns: Tauto config dict.
    """
    self._api.file.write_proto('write skylab_test_runner result',
                               test_runner_result_file_path, test_runner_result,
                               'JSONPB')
    config = {
        'result_format': 'skylab-test-runner',
        'base_variant': metadata.rdb_base_variant,
        'base_tags': metadata.rdb_base_tags,
        'result_file': test_runner_result_file_path,
        'artifact_directory': None,
        'force_current_realm': force_current_realm
    }
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
        test = line.split('=')[-1]
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
        [CrosToolRunnerPrejobDUTResponse.build_aborted_response('dut')], True)

  def process_test_responses(self, cros_test_responses):
    """Process test responses from run_test.

    Args:
    * cros_test_responses (TestResponse):  Test responses from run_test.

    Returns:
      processed test responses tuple: (test_responses_for_output_props, test_response_for_result_uploading)
    """
    with self._api.step.nest("Processing CTR Test Responses") as step:
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
            "Output"] = "No tast_via_tauto found. So no processing required."
        return cros_test_responses, cros_test_responses

      for path, resp_list in path_to_tast_dut_resp_dict.items():
        for resp in resp_list:
          ret1.append(resp)
          ret1_ids.append(resp.data.test_case_id.value)
          if path not in path_to_tauto_dut_resp_dict:
            # If not tast_via_tauto, add this independant tast result to response.
            ret2.append(resp)
            ret2_ids.append(resp.data.test_case_id.value)

      step.presentation.logs["For_Output_Props_Test_Ids"] = ret1_ids
      step.presentation.logs["For_Result_Uploading_Test_Ids"] = ret2_ids

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
    # There will be only one of list(allow/block) at a given time, so the order
    # of below blocks doesn't matters.
    if fw_config.HasField("allow_list"):
      return (device.dut_model.build_target in fw_config.allow_list.boards or
              device.dut_model.model_name in fw_config.allow_list.models)
    if fw_config.HasField("block_list"):
      return (device.dut_model.build_target not in fw_config.block_list.boards
              and
              device.dut_model.model_name not in fw_config.block_list.models)
    # We shouldn't hit here ever, but for safe we return False if it happens.
    return False
