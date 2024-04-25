# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import copy
import datetime
import os
from google.protobuf import json_format as jsonpb
from recipe_engine.recipe_api import RecipeApi, StepFailure
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry
from PB.test_platform.taskstate import TaskState

SYS_LOG_DIR = '/var/log'
VM_ARTIFACT_TARBALL = '/tmp/artifacts.tar'
ARTIFACT_TARBALL_NAME = 'artifacts.tar'
VM_ARTIFACT_LIST = ['/var/log', '/var/spool/crash']
VM_ARTIFACT_TEMPDIR = '/tmp/vm-artifacts'
PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_test_image.bin'
QCOW_IMG_NAME = 'qcow2.img'
QEMU_VM_HOST = 'localhost'
QEMU_VM_PORT = '9222'
GCE_VM_PORT = '22'


class TastExecApi(RecipeApi):
  """A module to execute tast commands."""

  class TastInputs():
    """Common inputs for TastExecApi methods.

    Args:
      expressions (list[str]): Expressions describing tests to run.
      test_artifacts_dir (Path): Dir containing test artifacts.
      build_payload (BuildPayload): Where the build artifact is on GS.
      run_args (list[str]): Additional arguments to pass to the `tast run`
          command (optional).
      shard_args (list[str]): Arguments that indicate how the test should be
          sharded (optional). Note that this is split from run_args since these
          args need to be passed to both `tast run` and `tast list`.
    """

    def __init__(self, expressions, test_artifacts_dir, build_payload,
                 run_args=None, shard_args=None):
      self.expressions = expressions
      self.test_artifacts_dir = test_artifacts_dir
      self.build_payload = build_payload
      self.run_args = run_args or []
      self.shard_args = shard_args or []

    def copy(self):
      """Make a new TastInputs with the same field values."""
      return copy.deepcopy(self)

    def build_artifacts_url(self):
      """GS URL where the build artifacts are located."""
      return 'gs://{}/{}/'.format(self.build_payload.artifacts_gs_bucket,
                                  self.build_payload.artifacts_gs_path)

  class VmInfo():
    """Info about a VM that has been launched.

    Args:
      host (str): Host name or IP.
      port (str): SSH port.
      pid_file (Path): PID of the QEMU process, if available (optional).
    """

    def __init__(self, host, port, pid_file=None):
      self.host = host
      self.port = port
      self.pid_file = pid_file

    def address(self):
      """Get a "host:port" connection string.

      Returns:
        str: Connection string.
      """
      return '{}:{}'.format(self.host, self.port)

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._exec_timeout = properties.exec_timeout or 90 * 60
    self._vm_system_services_timeout = properties.vm_system_services_timeout or 10 * 60
    self._public_builder = properties.public_builder
    self._tast_cli_supported_flags = []
    self._sshkeys = []
    # We create this directory on first call to add_ssh_key.
    self._sshkeys_dir = None

  def add_ssh_key(self, path):
    """Registers an SSH key for use during test execution.

    Args:
      path (Path): Path to the SSH key.
    """
    if self._sshkeys_dir is None:
      self._sshkeys_dir = self.m.path.mkdtemp(prefix='sshkeys_dir')

    name = self.m.path.basename(path)
    newpath = self.m.path.join(self._sshkeys_dir, name)
    self.m.file.copy('copy ssh key ({})'.format(name), path, newpath)
    self.m.file.chmod('calibrate ssh key permissions ({})'.format(name),
                      newpath, '400')
    self._sshkeys.append(newpath)

  def fetch_partner_key(self):
    """Fetch partner key from private ChromeOS Tree"""
    with self.m.step.nest('fetch partner ssh key for chromeos images'):
      sshkeys_dir = self.m.path.mkdtemp(prefix='sshkeys')
      self.m.git.clone(
          'https://chrome-internal.googlesource.com/chromeos/sshkeys',
          branch='main', target_path=sshkeys_dir, depth=1)
      partner_key_path = sshkeys_dir / 'partner_testing_rsa'
      self.add_ssh_key(partner_key_path)

  def download_tast(self, build_payload, test_artifacts_dir):
    """Downloads the tast executable from specified build artifacts.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      test_artifacts_dir (str): The directory to which files should be
        downloaded. The tast executable will be found at tast/tast relative
        to this directory.
    """
    with self.m.step.nest('setup tast') as presentation:
      presentation.text = 'download tast executable'
      sp_tar_file = test_artifacts_dir / 'autotest_server_package.tar.bz2'
      archive_path = os.path.join(build_payload.artifacts_gs_path,
                                  'autotest_server_package.tar.bz2')
      self.m.gsutil.download(build_payload.artifacts_gs_bucket, archive_path,
                             sp_tar_file, name='download tast bundle from GS')
      self.m.step(
          'untar tast',
          ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  def download_vm(self, build_payload, vm_dir, modify_image=None):
    """Downloads the VM image from specified build artifacts.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      vm_dir (Path): The directory to which files should be
        downloaded.
      modify_image (func): Function that takes one argument, the VM
        image path. It will be called prior to converting the raw image
        to the qcow2 format. (optional).

    Returns:
      The location of the qcow image. This will be a location inside
        image_archive_dir.
    """
    with self.m.step.nest('setup vm image'):
      test_image_zip = vm_dir / 'image.zip'
      test_image_dir = vm_dir / 'image'
      vm_image_path = test_image_dir / VM_IMAGE_NAME
      qcow_image_path = test_image_dir / QCOW_IMG_NAME
      private_key_path = test_image_dir / PRIVATE_KEY_NAME
      self.m.gsutil.download(
          build_payload.artifacts_gs_bucket,
          os.path.join(build_payload.artifacts_gs_path, 'image.zip'),
          test_image_zip, name='download image bundle from GS')
      self.m.archive.extract('unzip image bundle', test_image_zip,
                             test_image_dir,
                             include_files=[VM_IMAGE_NAME, PRIVATE_KEY_NAME])

      if modify_image:
        modify_image(vm_image_path)

      self.m.step('convert image to qcow format', [
          'qemu-img', \
          'create', \
          '-f', 'qcow2', \
          '-F', 'raw', \
          '-b', str(vm_image_path), \
          str(qcow_image_path) \
      ])
      if self.m.path.exists(private_key_path):  # pragma: nocover
        self.add_ssh_key(private_key_path)
      self.fetch_partner_key()

    return qcow_image_path

  def run_vm(self, suite_name, vm_context, tast_inputs):
    """Run tast tests in a VM with one retry and upload logs to Google storage.

    Args:
      suite_name (str): Unique name used to record test results.
      vm_context (contextlib.contextmanager): The VM context manager, created
        by create_qemu_vm_context/create_gce_vm_context.
      tast_inputs (TastInputs): Common inputs for running tast tests.

    Returns:
      A tuple of list(Failures), a bool indicating whether the results were
       empty and a dict mapping a task kind with the number of successes.
    """
    task_result = self._retry_iter(suite_name, vm_context, tast_inputs, 'first')
    tests_to_retry, _ = self.m.tast_results.get_tests_to_retry(task_result)
    all_test_cases = []
    if task_result.test_cases:
      all_test_cases = jsonpb.MessageToDict(task_result)['testCases']
    tests_to_retry = tests_to_retry if self.m.buildbucket.is_critical() else []
    results, failed_test_cases = self.m.tast_results.convert_results(
        task_result, tests_to_retry)
    empty_result = task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
    if tests_to_retry:
      tast_inputs = tast_inputs.copy()
      tast_inputs.expressions = tests_to_retry
      retry_task_result = self._retry_iter(suite_name, vm_context, tast_inputs,
                                           'second', new_invocation=True)
      if retry_task_result.test_cases:
        all_test_cases += jsonpb.MessageToDict(retry_task_result)['testCases']
      retry_results, retry_tcs = self.m.tast_results.convert_results(
          retry_task_result)
      empty_result = \
          retry_task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      results.add_results(retry_results)
      failed_test_cases += retry_tcs

    self.m.easy.set_properties_step(all_test_cases=all_test_cases,
                                    failed_test_cases=failed_test_cases)
    if all_test_cases:
      passed_tc_count = len(all_test_cases) - len(failed_test_cases)
      greenness = int(100 * passed_tc_count / len(all_test_cases))
      self.m.easy.set_properties_step(greenness=greenness)
    self.m.tast_results.record_logs(SYS_LOG_DIR)

    return results, empty_result

  def _retry_iter(self, suite_name, vm_context, tast_inputs, tag,
                  new_invocation=False):
    with self.m.step.nest('%s tast iteration' % tag) as pres:
      test_results_dir = self.m.path.mkdtemp(prefix='test-results')
      tests = self.run_direct_vm(vm_context, test_results_dir, tast_inputs)
      pres.logs['tests'] = tests
      return self.m.tast_results.get_results(test_results_dir, suite_name, tag,
                                             tests,
                                             tast_inputs.build_artifacts_url(),
                                             new_invocation=new_invocation)

  def _amend_tast_inputs(self, tast_inputs: TastInputs) -> TastInputs:
    """Modifies TastInputs based on the given Tast version.

    Ensures that newer flags are not passed in when running Tast on images
    created using an older source.

    Currently checks for the existance of the following flags:
      * systemservicestimeout:
          Not passed in by default, added if it is supported.
      * shardmethod:
          Passed in by default, removed if it is not supported.

    Args:
      TastInputs: Inputs for executing Tast.

    Returns:
      A copy of TastInputs with potentially modified flags.
    """
    tast_inputs = tast_inputs.copy()
    if self._flag_exists(tast_inputs.test_artifacts_dir / 'tast',
                         'systemservicestimeout'):
      tast_inputs.run_args.append('-systemservicestimeout={}'.format(
          self._vm_system_services_timeout))

    # Check if the shardmethod flag exists before passing it in.
    if not self._flag_exists(tast_inputs.test_artifacts_dir / 'tast',
                             'shardmethod'):
      tast_inputs.shard_args = [
          x for x in tast_inputs.shard_args if not x.startswith('-shardmethod')
      ]

    return tast_inputs

  def run_direct_vm(self, vm_context, test_results_dir, tast_inputs):
    """Run tast tests in a VM without retries or results processing.

    Args:
      vm_context (contextlib.contextmanager): The VM context manager, created
        by create_qemu_vm_context/create_gce_vm_context.
      test_results_dir (Path): Path to store tast results.
      tast_inputs (TastInputs): Common inputs for running tast tests.
      new_invocation (bool): Whether the test results should be uploaded in a
          new invocation.

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    tast_inputs = self._amend_tast_inputs(tast_inputs)

    # Entering vm_context instantiates the VM we are to test against. The VM
    # is cleaned up automatically when exiting the context.
    with vm_context() as vm:
      tests = self.run_direct(vm.address(), tast_inputs, test_results_dir)

      # b/219966100: Occasionally the `tast run` step will leave the VM in an
      # unresponsive state. Make sure we can establish an SSH connection before
      # attempting to archive artifacts.
      self._test_ssh_conn(vm.host, vm.port)
      # Add logs and other artifacts from DUT into the test results directory.
      self._archive_vm_artifacts(vm.host, vm.port, test_results_dir)

    return tests

  def run_direct(self, dut_name, tast_inputs, test_results_dir):
    """Run tast tests without retries or results processing.

    Args:
      dut_name (str): The identity of the DUT to connect to,
        for example, my-dut-host-name or localhost:9222 (if testing a VM).
      tast_inputs (TastInputs): Common inputs for running tast tests.
      test_results_dir (Path): Path to store tast results.

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    # Used by tast to determine where to download private bundles.
    tast_inputs = tast_inputs.copy()
    tast_inputs.test_artifacts_dir = tast_inputs.test_artifacts_dir / 'tast'
    tests = self._list_tests(dut_name, tast_inputs)
    if tests:
      self._run_tests(dut_name, tast_inputs, test_results_dir)
    return tests

  def _get_ssh_conn_args(self):
    args = [
       '-oConnectionAttempts=4', \
       '-oUserKnownHostsFile=/dev/null', \
       '-oProtocol=2', \
       '-oConnectTimeout=30', \
       '-oServerAliveCountMax=8', \
       '-oStrictHostKeyChecking=no', \
       '-oServerAliveInterval=15', \
       '-oNumberOfPasswordPrompts=0', \
       '-oIdentitiesOnly=yes']
    for p in self._sshkeys:
      args += ['-i', p]
    return args

  def _get_scp_cmd(self, host, port, remote_path, local_path):
    return ['scp', '-P', port] + self._get_ssh_conn_args() + \
        ['root@{}:{}'.format(host, remote_path), local_path]

  def _get_ssh_cmd(self, host, port, cmd):
    return ['ssh', '-p', port] + self._get_ssh_conn_args() + \
        ['root@{}'.format(host), '--'] + cmd

  def _archive_vm_artifacts(self, host, port, output_dir):
    # b/204628226: Work-around tar's (non) handling of open file descriptors by
    # rsyncing artifacts to a temporary location before tarring.
    cmd = self._get_ssh_cmd(host, port,
                            ['rsync', '--links', '--recursive'] + \
                            VM_ARTIFACT_LIST + [VM_ARTIFACT_TEMPDIR])
    self.m.step('rsync artifacts to a temporary location on the VM', cmd,
                infra_step=True, timeout=5 * 60)
    cmd = self._get_ssh_cmd(
        host, port,
        ['tar', 'cf', VM_ARTIFACT_TARBALL, '{}/*'.format(VM_ARTIFACT_TEMPDIR)])
    self.m.step('gather artifacts on VM', cmd, infra_step=True, timeout=5 * 60)
    # Remove the tempdir.
    self.m.file.remove('remove temporary artifacts', VM_ARTIFACT_TEMPDIR)
    cmd = self._get_scp_cmd(host, port, VM_ARTIFACT_TARBALL,
                            str(output_dir / ARTIFACT_TARBALL_NAME))
    self.m.step('download artifacts from VM', cmd, infra_step=True,
                timeout=5 * 60)

  def _list_tests(self, dut_name, tast_inputs):
    tast_dir = tast_inputs.test_artifacts_dir
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)
    keydir_args = ['-keydir={}'.format(self._sshkeys_dir)
                  ] if self._sshkeys_dir else []

    list_stdout = self.m.easy.stdout_step('tast list', [
        str(tast_dir / 'tast'), \
        'list', \
        '-build=false', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(tast_inputs.build_artifacts_url()), \
        '-remotebundledir={}'.format(
            str(tast_dir.joinpath('bundles').joinpath('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir / 'data')), \
        '-remoterunner={}'.format(
            str(tast_dir / 'remote_test_runner'))] + \
    keydir_args + \
    tast_inputs.shard_args + \
    [dut_name] + \
    list(tast_inputs.expressions), timeout=5 * 60,
    test_stdout=self._test_data.get('simulate_test_list_ret')).decode('utf-8')

    tests = [t.strip() for t in list_stdout.splitlines()]
    return tests

  def _flag_exists(self, tast_dir, flag_name):
    if not self._tast_cli_supported_flags:
      tast_help_stdout = self.m.easy.stdout_step('tast help run', [
          str(tast_dir / 'tast'), \
          'help', \
          'run'], test_stdout='-shardmethod\n-systemservicestimeout').decode('utf-8')
      self._tast_cli_supported_flags = [
          t.strip().split(' ')[0]
          for t in tast_help_stdout.splitlines()
          if t.strip().startswith('-')
      ]
    # append '-' in the beginning if do not exist
    if not flag_name.startswith('-'):
      flag_name = '-{}'.format(flag_name)
    return flag_name in self._tast_cli_supported_flags

  def _run_tests(self, dut_name, tast_inputs, test_results_dir):
    tast_dir = tast_inputs.test_artifacts_dir
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)
    maybemissingvars_args = []
    if self._public_builder:
      maybemissingvars_args = [r'-maybemissingvars=.+\..+']
    keydir_args = ['-keydir={}'.format(self._sshkeys_dir)
                  ] if self._sshkeys_dir else []

    self.m.step('tast run', [
        str(tast_dir / 'tast'), \
        '-verbose', \
        'run', \
        '-build=false', \
        '-sshretries=2', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(tast_inputs.build_artifacts_url()), \
        '-waituntilready', \
        '-continueafterfailure', \
        '-extrauseflags=tast_vm', \
        '-var=setup.FieldTrialConfig=disable',
        '-defaultvarsdir={}'.format(str(tast_dir / 'vars')), \
        '-resultsdir', str(test_results_dir), \
        '-remotebundledir={}'.format(
            str(tast_dir.joinpath('bundles').joinpath('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir / 'data')), \
        '-remoterunner={}'.format(
            str(tast_dir / 'remote_test_runner'))] + \
        keydir_args + \
        maybemissingvars_args + \
        tast_inputs.run_args + \
        tast_inputs.shard_args + \
        [dut_name] + \
        list(tast_inputs.expressions), ok_ret='any', timeout=self._exec_timeout)

  def create_qemu_vm_context(self, qcow_image_path, second_image_path=None):
    """Creates a context manager which performs setup/teardown of a QEMU VM.

    Args:
      qcow_image_path (Path): Path to image in qcow format.
      second_image_path (Path): Path to a second qcow disk image (optional).

    Returns:
      A context manager that
        - when entered, prepares a VM to test against, and yields a
          VmInfo object for connecting to it.
        - when exited, terminates the VM and performs cleanup.
    """

    @contextlib.contextmanager
    def qemu_vm_context():
      kvm_pid_file = self.m.path.mkstemp(prefix='kvm-pid')
      kvm_monitor_file = self.m.path.mkstemp(prefix='kvm-monitor')
      kvm_monitor_serial_file = self.m.path.mkstemp(prefix='kvm-monitor-serial')
      overlay_dir = self.m.path.mkdtemp(prefix='image-overlay')
      overlay_image_path = overlay_dir / QCOW_IMG_NAME

      self._launch_vm(qcow_image_path, overlay_image_path, kvm_pid_file,
                      kvm_monitor_file, kvm_monitor_serial_file,
                      second_image_path)
      try:
        yield TastExecApi.VmInfo(QEMU_VM_HOST, QEMU_VM_PORT, kvm_pid_file)
      finally:
        try:
          # Always kill QEMU.
          self._kill_vm(kvm_pid_file, overlay_image_path)
        finally:
          self._record_qemu_logs(kvm_monitor_file, kvm_monitor_serial_file)

    return qemu_vm_context

  @exponential_retry(retries=1, delay=datetime.timedelta(seconds=1))
  def _launch_vm(self, qcow_image_path, overlay_image_path, kvm_pid_file,
                 kvm_monitor_file, kvm_monitor_serial_file, second_image_path):
    self.m.step('create qcow image overlay', [
        'qemu-img', \
        'create', \
        '-f', 'qcow2', \
        '-F', 'qcow2', \
        '-b', str(qcow_image_path), \
        str(overlay_image_path) \
    ])

    n_proc = self.m.easy.stdout_step(
        'count online CPUs', ['nproc'],
        test_stdout=' 8\n').decode('utf-8').strip()
    qemu_args = [
        '/usr/bin/qemu-system-x86_64', \
        '-m', '8G', \
        '-smp', n_proc, \
        '-vga', 'virtio', \
        '-daemonize', \
        '-usbdevice', 'tablet', \
        '-pidfile', str(kvm_pid_file), \
        '-chardev', 'pipe,id=control_pipe,path={}'.format(
            str(kvm_monitor_file)), \
        '-serial', 'file:{}'.format(str(kvm_monitor_serial_file)), \
        '-mon', 'chardev=control_pipe', \
        '-cpu', 'SandyBridge,-invpcid,-tsc-deadline,check,vmx=on', \
        '-device', 'virtio-net,netdev=eth0', \
        '-device', 'virtio-scsi-pci,id=scsi', \
        '-device', 'virtio-rng', \
        '-device', 'scsi-hd,drive=hd', \
        '-drive',
        'if=none,id=hd,file={},cache=unsafe,format=qcow2'.format(
            overlay_image_path), \
        '-netdev', \
        'user,id=eth0,net=10.0.2.0/27,hostfwd=tcp:127.0.0.1:{}-:22'.format(
            QEMU_VM_PORT), \
        '-enable-kvm', \
        '-display', 'none'
    ]
    if second_image_path is not None:
      # The second device is attached the same way as the first, but
      # with the default caching mode instead of "unsafe" to ensure that
      # writes make it out to the image.
      qemu_args += [
          '-device', 'scsi-hd,drive=hd2', '-drive',
          'if=none,id=hd2,file={},format=qcow2'.format(second_image_path)
      ]

    self.m.step('launch image as vm', qemu_args, infra_step=True)
    try:
      self._test_ssh_conn(QEMU_VM_HOST, QEMU_VM_PORT)
    except StepFailure:  # pragma: nocover
      self._kill_vm(kvm_pid_file, overlay_image_path)
      raise

  def is_vm_running(self, kvm_pid_file):
    """Check if the specified PID is still running.

    Args:
      kvm_pid_file (Path): File containing the PID of a QEMU process.

    Returns:
      bool: Whether the VM process is still running.
    """
    # Exits zero if the PID is still running, exits one if not. (Any
    # other return code indicates an unexpected error).
    result = self.m.step('check if VM running', ['pgrep', '-F', kvm_pid_file],
                         infra_step=True, ok_ret=(0, 1))
    return result.retcode == 0

  def _kill_vm(self, kvm_pid_file, overlay_image_path):
    # Don't try to kill the VM if it has already exited.
    if self.is_vm_running(kvm_pid_file):
      self.m.step('kill vm', ['pkill', '-F', kvm_pid_file])
    self.m.file.remove('remove overlay image', overlay_image_path)

  def _record_qemu_logs(self, kvm_monitor_file, kvm_monitor_serial_file):
    with self.m.step.nest('qemu logs') as presentation:
      presentation.logs['kvm.monitor'] = self.m.file.read_text(
          'reading file', kvm_monitor_file)
      presentation.logs['kvm.monitor.serial'] = self.m.file.read_text(
          'reading file', kvm_monitor_serial_file)

  def create_gce_vm_context(self, image, project, machine, zone, network,
                            subnet):
    """Creates a context manager which performs setup/teardown of a GCE VM.

    Args:
      image(str): GCE image to use for the instance.
      project(str): Google Cloud project name.
      machine(str): GCE machine type
      zone(str): GCE zone to create instance (e.g. us-central1-b).
      network(str): Network name to use.
      subnet(str): Network subnet on which to create instance.

    Returns:
      A context manager that
        - when entered, prepares a VM to test against, and yields a
          VmInfo object for connecting to it.
        - when exited, terminates the VM and performs cleanup.
    """

    @contextlib.contextmanager
    def gce_vm_context():
      instance, ip_addr, _ = self.m.gcloud.create_instance(
          image, project, machine, zone, network, subnet)
      try:
        self._test_ssh_conn(ip_addr, GCE_VM_PORT)
        yield TastExecApi.VmInfo(ip_addr, GCE_VM_PORT)
      finally:
        try:
          self.m.gcloud.get_instance_serial_output(instance, project, zone)
        finally:
          # Ignore any exceptions when deleting the instance as to not block
          # test result reporting.
          with self.m.failures.ignore_exceptions():
            self.m.gcloud.delete_instance(instance, project, zone)

    return gce_vm_context

  @exponential_retry(retries=3, delay=datetime.timedelta(minutes=1))
  def _test_ssh_conn(self, host, port):
    cmd = self._get_ssh_cmd(host, port, ['true'])
    try:
      self.m.step('connect via ssh', cmd, timeout=5 * 60)
    except StepFailure as e:
      raise StepFailure('Could not connect to the vm instance. This can be '
                        'because the change being tested caused an error '
                        'during boot or potentially an infrastructure '
                        'failure.') from e
