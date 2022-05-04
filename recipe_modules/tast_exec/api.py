# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import os
from google.protobuf import json_format as jsonpb
from recipe_engine.recipe_api import RecipeApi, StepFailure
from RECIPE_MODULES.chromeos.util.util import exponential_retry
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

  def __init__(self, properties, *args, **kwargs):
    super(TastExecApi, self).__init__(*args, **kwargs)
    self._exec_timeout = properties.exec_timeout or 90 * 60
    self._vm_system_services_timeout = properties.vm_system_services_timeout or 10 * 60
    self._should_retry = properties.should_retry
    self._public_builder = properties.public_builder
    self._tast_cli_supported_flags = []

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
      sp_tar_file = test_artifacts_dir.join('autotest_server_package.tar.bz2')
      archive_path = os.path.join(build_payload.artifacts_gs_path,
                                  'autotest_server_package.tar.bz2')
      self.m.gsutil.download(build_payload.artifacts_gs_bucket, archive_path,
                             sp_tar_file, name='download tast bundle from GS')
      self.m.step(
          'untar tast',
          ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  def download_vm(self, build_payload, vm_dir):
    """Downloads the VM image from specified build artifacts.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      vm_dir (Path): The directory to which files should be
        downloaded.

    Returns:
      qcow_image_path (Path): The location of the qcow image. This will be
        a location inside image_archive_dir.
      private_key_path (Path): The location of the SSH key. This will be
        a location inside image_archive_dir.
    """
    with self.m.step.nest('setup vm image'):
      test_image_zip = vm_dir.join('image.zip')
      test_image_dir = vm_dir.join('image')
      vm_image_path = test_image_dir.join(VM_IMAGE_NAME)
      qcow_image_path = test_image_dir.join(QCOW_IMG_NAME)
      private_key_path = test_image_dir.join(PRIVATE_KEY_NAME)
      self.m.gsutil.download(
          build_payload.artifacts_gs_bucket,
          os.path.join(build_payload.artifacts_gs_path, 'image.zip'),
          test_image_zip, name='download image bundle from GS')
      self.m.archive.extract('unzip image bundle', test_image_zip,
                             test_image_dir,
                             include_files=[VM_IMAGE_NAME, PRIVATE_KEY_NAME])

      self.m.step('convert image to qcow format', [
          'qemu-img', \
          'create', \
          '-f', 'qcow2', \
          '-b', str(vm_image_path), \
          str(qcow_image_path) \
      ])
      self.m.step('calibrate ssh key permissions',
                  ['chmod', '400', str(private_key_path)])
    return qcow_image_path, private_key_path

  def run_vm(self, suite_name, expressions, vm_context, test_artifacts_dir,
             private_key_path, build_payload):
    """Run tast tests in a VM with one retry and upload logs to Google storage.

    Args:
      suite_name (str): Unique name used to record test results.
      expressions (list[str]): Expressions to test.
      vm_context (contextlib.contextmanager): The VM context manager, created
        by create_qemu_vm_context/create_gce_vm_context.
      test_artifacts_dir (Path): Dir containing test artifacts.
      private_key_path (Path): Path to private key.
      build_payload (BuildPayload): Describes where the artifact is on GS.

    Returns:
      A tuple of list(Failures) and a bool indicating whether
        the results were empty.
    """
    task_result = self._retry_iter(suite_name, expressions, vm_context,
                                   test_artifacts_dir, private_key_path,
                                   'first', build_payload)
    tests_to_retry, _ = self.m.tast_results.get_tests_to_retry(task_result)
    all_test_cases = []
    if task_result.test_cases:
      all_test_cases = jsonpb.MessageToDict(task_result)['testCases']
    if not self._should_retry:
      tests_to_retry = []
    failures, failed_test_cases = self.m.tast_results.get_failures(
        task_result, tests_to_retry)
    empty_result = task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
    if tests_to_retry:
      retry_task_result = self._retry_iter(suite_name, tests_to_retry,
                                           vm_context, test_artifacts_dir,
                                           private_key_path, 'second',
                                           build_payload)
      all_test_cases += jsonpb.MessageToDict(retry_task_result)['testCases']
      retry_failures, retry_tcs = self.m.tast_results.get_failures(
          retry_task_result)
      empty_result = \
          retry_task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      failures += retry_failures
      failed_test_cases += retry_tcs

    self.m.easy.set_properties_step(all_test_cases=all_test_cases,
                                    failed_test_cases=failed_test_cases)
    if all_test_cases:
      passed_tc_count = len(all_test_cases) - len(failed_test_cases)
      greenness = int(100 * passed_tc_count / len(all_test_cases))
      self.m.easy.set_properties_step(greenness=greenness)
    self.m.tast_results.record_logs(SYS_LOG_DIR)

    return failures, empty_result

  def _retry_iter(self, suite_name, expressions, vm_context, test_artifacts_dir,
                  private_key_path, tag, build_payload):
    with self.m.step.nest('%s tast iteration' % tag):
      test_results_dir = self.m.path.mkdtemp(prefix='test-results')
      tests = self.run_direct_vm(expressions, vm_context, test_artifacts_dir,
                                 private_key_path, build_payload,
                                 test_results_dir)
      return self.m.tast_results.get_results(test_results_dir, suite_name, tag,
                                             tests)

  def run_direct_vm(self, expressions, vm_context, test_artifacts_dir,
                    private_key_path, build_payload, test_results_dir,
                    run_args=None):
    """Run tast tests in a VM without retries or results processing.

    Args:
      expressions (list[str]): Expressions describing tests to run.
      vm_context (contextlib.contextmanager): The VM context manager, created
        by create_qemu_vm_context/create_gce_vm_context.
      test_artifacts_dir (Path): Dir containing test artifacts.
      private_key_path (Path): Path to private key.
      build_payload (BuildPayload): Describes where the artifact is on GS.
      test_results_dir (Path): Path to store tast results.
      run_args (list[str]): Additional arguments to pass to tast (optional).

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    if run_args is None:
      run_args = []
    else:
      run_args = list(run_args)
    if self._flag_exists(
        test_artifacts_dir.join('tast'), 'systemservicestimeout'):
      run_args.append('-systemservicestimeout={}'.format(
          self._vm_system_services_timeout))  # pragma: no cover

    # Entering vm_context instantiates the VM we are to test against. The VM
    # is cleaned up automatically when exiting the context.
    with vm_context() as (host, port):
      tests = self.run_direct('{}:{}'.format(host, port), expressions,
                              test_artifacts_dir, build_payload,
                              test_results_dir,
                              private_key_path=private_key_path,
                              run_args=run_args)

      # b/219966100: Occasionally the `tast run` step will leave the VM in an
      # unresponsive state. Make sure we can establish an SSH connection before
      # attempting to archive artifacts.
      self.m.step('connect via ssh',
                  self._get_ssh_cmd(host, port, private_key_path, ['true']))

      # Add logs and other artifacts from DUT into the test results directory.
      self._archive_vm_artifacts(host, port, private_key_path, test_results_dir)
    return tests

  def run_direct(self, dut_name, expressions, test_artifacts_dir, build_payload,
                 test_results_dir, private_key_path=None, run_args=None):
    """Run tast tests without retries or results processing.

    Args:
      dut_name (str): The identity of the DUT to connect to,
        for example, my-dut-host-name or localhost:9222 (if testing a VM).
      expressions (list[str]): Expressions describing tests to run.
      test_artifacts_dir (Path): Dir containing test artifacts.
      build_payload (BuildPayload): Describes where the artifact is on GS.
      test_results_dir (Path): Path to store tast results.
      private_key_path (Path): Path to private key to use (optional).
      run_args (list[str]): Additional arguments to pass to tast (optional).

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    # Used by tast to determine where to download private bundles.
    build_artifacts_url = 'gs://{}/{}/'.format(
        build_payload.artifacts_gs_bucket, build_payload.artifacts_gs_path)
    tast_dir = test_artifacts_dir.join('tast')
    tests = self._list_tests(dut_name, expressions, tast_dir, private_key_path,
                             build_artifacts_url)
    self._run_tests(dut_name, expressions, tast_dir, private_key_path,
                    build_artifacts_url, test_results_dir, run_args)
    return tests

  @staticmethod
  def _get_ssh_conn_args(private_key_path):
    return [
       '-oConnectionAttempts=4', \
       '-oUserKnownHostsFile=/dev/null', \
       '-oProtocol=2', \
       '-oConnectTimeout=30', \
       '-oServerAliveCountMax=8', \
       '-oStrictHostKeyChecking=no', \
       '-oServerAliveInterval=15', \
       '-oNumberOfPasswordPrompts=0', \
       '-oIdentitiesOnly=yes', \
       '-i', private_key_path]

  def _get_scp_cmd(self, host, port, private_key_path, remote_path, local_path):
    return ['scp', '-P', port] + self._get_ssh_conn_args(private_key_path) + \
        ['root@{}:{}'.format(host, remote_path), local_path]

  def _get_ssh_cmd(self, host, port, private_key_path, cmd):
    return ['ssh', '-p', port] + self._get_ssh_conn_args(private_key_path) + \
        ['root@{}'.format(host), '--'] + cmd

  def _archive_vm_artifacts(self, host, port, private_key_path, output_dir):
    # b/204628226: Work-around tar's (non) handling of open file descriptors by
    # rsyncing artifacts to a temporary location before tarring.
    cmd = self._get_ssh_cmd(host, port, private_key_path,
                            ['rsync', '--links', '--recursive'] + \
                            VM_ARTIFACT_LIST + [VM_ARTIFACT_TEMPDIR])
    self.m.step('rsync artifacts to a temporary location on the VM', cmd,
                infra_step=True, timeout=5 * 60)
    cmd = self._get_ssh_cmd(
        host, port, private_key_path,
        ['tar', 'cf', VM_ARTIFACT_TARBALL, '{}/*'.format(VM_ARTIFACT_TEMPDIR)])
    self.m.step('gather artifacts on VM', cmd, infra_step=True, timeout=5 * 60)
    # Remove the tempdir.
    self.m.file.remove('remove temporary artifacts', VM_ARTIFACT_TEMPDIR)
    cmd = self._get_scp_cmd(host, port, private_key_path, VM_ARTIFACT_TARBALL,
                            str(output_dir.join(ARTIFACT_TARBALL_NAME)))
    self.m.step('download artifacts from VM', cmd, infra_step=True,
                timeout=5 * 60)

  def _list_tests(self, dut_name, expressions, tast_dir, private_key_path,
                  build_artifacts_url):
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)
    keyfile_args = []
    if private_key_path is not None:
      keyfile_args = ['-keyfile={}'.format(private_key_path)]

    list_stdout = self.m.easy.stdout_step('tast list', [
        str(tast_dir.join('tast')), \
        'list', \
        '-build=false', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(build_artifacts_url), \
        '-remotebundledir={}'.format(
            str(tast_dir.join('bundles').join('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir.join('data'))), \
        '-remoterunner={}'.format(
            str(tast_dir.join('remote_test_runner')))] + \
    keyfile_args + \
    [dut_name] + \
    list(expressions), timeout=5 * 60)

    tests = [t.strip() for t in list_stdout.splitlines()]
    return tests

  def _flag_exists(self, tast_dir, flag_name):
    if not self._tast_cli_supported_flags:
      tast_help_stdout = self.m.easy.stdout_step('tast help run', [
          str(tast_dir.join('tast')), \
          'help', \
          'run'])
      self._tast_cli_supported_flags = [
          t.strip().split(' ')[0]
          for t in tast_help_stdout.splitlines()
          if t.strip().startswith('-')
      ]
    # append '-' in the beginning if do not exist
    if not flag_name.startswith('-'):
      flag_name = '-{}'.format(flag_name)
    return flag_name in self._tast_cli_supported_flags

  def _run_tests(self, dut_name, expressions, tast_dir, private_key_path,
                 build_artifacts_url, test_results_dir, extra_args):
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)
    maybemissingvars_args = []
    if self._public_builder:
      maybemissingvars_args = [r'-maybemissingvars=.+\..+']
    keyfile_args = []
    if private_key_path is not None:
      keyfile_args = ['-keyfile={}'.format(private_key_path)]

    self.m.step('tast run', [
        str(tast_dir.join('tast')), \
        '-verbose', \
        'run', \
        '-build=false', \
        '-sshretries=2', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(build_artifacts_url), \
        '-waituntilready', \
        '-continueafterfailure', \
        '-extrauseflags=tast_vm', \
        '-defaultvarsdir={}'.format(str(tast_dir.join('vars'))), \
        '-resultsdir', str(test_results_dir), \
        '-remotebundledir={}'.format(
            str(tast_dir.join('bundles').join('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir.join('data'))), \
        '-remoterunner={}'.format(
            str(tast_dir.join('remote_test_runner')))] + \
        keyfile_args + \
        maybemissingvars_args + \
        extra_args + \
        [dut_name] + \
        list(expressions), ok_ret='any', timeout=self._exec_timeout)

  def create_qemu_vm_context(self, qcow_image_path, private_key_path):
    """Creates a context manager which performs setup/teardown of a QEMU VM.

    Args:
      qcow_image_path (Path): Path to image in qcow format.
      private_key_path (Path): Path to private key.

    Returns:
      A context manager that
        - when entered, prepares a VM to test against, and yields the
          (host, port) for connecting to it.
        - when exited, terminates the VM and performs cleanup.
    """

    @contextlib.contextmanager
    def qemu_vm_context():
      kvm_pid_file = self.m.path.mkstemp(prefix='kvm-pid')
      kvm_monitor_file = self.m.path.mkstemp(prefix='kvm-monitor')
      kvm_monitor_serial_file = self.m.path.mkstemp(prefix='kvm-monitor-serial')

      self._launch_vm(qcow_image_path, kvm_pid_file, kvm_monitor_file,
                      kvm_monitor_serial_file, private_key_path)
      try:
        yield QEMU_VM_HOST, QEMU_VM_PORT
      finally:
        try:
          # Always kill QEMU.
          self._kill_vm(kvm_pid_file)
        finally:
          self._record_qemu_logs(kvm_monitor_file, kvm_monitor_serial_file)

    return qemu_vm_context

  @exponential_retry(retries=2)
  def _launch_vm(self, qcow_image_path, kvm_pid_file, kvm_monitor_file,
                 kvm_monitor_serial_file, private_key_path):
    self.m.step('launch image as vm', [
        '/usr/bin/qemu-system-x86_64', \
        '-m', '8G', \
        '-smp', '8', \
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
            qcow_image_path), \
        '-netdev', \
        'user,id=eth0,net=10.0.2.0/27,hostfwd=tcp:127.0.0.1:{}-:22'.format(
            QEMU_VM_PORT), \
        '-enable-kvm', \
        '-display', 'none'
    ], infra_step=True)
    try:
      self._test_ssh_conn(QEMU_VM_HOST, QEMU_VM_PORT, private_key_path)
    except StepFailure:  # pragma: nocover
      self._kill_vm(kvm_pid_file)
      raise

  def _kill_vm(self, kvm_pid_file):
    self.m.step('kill vm', ['pkill', '-F', kvm_pid_file])

  def _record_qemu_logs(self, kvm_monitor_file, kvm_monitor_serial_file):
    with self.m.step.nest('qemu logs') as presentation:
      presentation.logs['kvm.monitor'] = self.m.file.read_text(
          'reading file', kvm_monitor_file)
      presentation.logs['kvm.monitor.serial'] = self.m.file.read_text(
          'reading file', kvm_monitor_serial_file)

  def create_gce_vm_context(self, image, project, machine, zone, network,
                            subnet, private_key_path):
    """Creates a context manager which performs setup/teardown of a GCE VM.

    Args:
      image(str): GCE image to use for the instance.
      project(str): Google Cloud project name.
      machine(str): GCE machine type
      zone(str): GCE zone to create instance (e.g. us-central1-b).
      network(str): Network name to use.
      subnet(str): Network subnet on which to create instance.
      private_key_path (Path): Path to private key.

    Returns:
      A context manager that
        - when entered, prepares a VM to test against, and yields the
          (host, port) for connecting to it.
        - when exited, terminates the VM and performs cleanup.
    """

    @contextlib.contextmanager
    def gce_vm_context():
      instance, ip_addr = self.m.gcloud.create_instance(image, project, machine,
                                                        zone, network, subnet)
      try:
        self._test_ssh_conn(ip_addr, GCE_VM_PORT, private_key_path)
        yield ip_addr, GCE_VM_PORT
      finally:
        try:
          self.m.gcloud.get_instance_serial_output(instance, project, zone)
        finally:
          self.m.gcloud.delete_instance(instance, project, zone)

    return gce_vm_context

  def _test_ssh_conn(self, host, port, private_key_path):
    cmd = self._get_ssh_cmd(host, port, private_key_path, ['true'])
    self.m.step('connect via ssh', cmd, infra_step=True, timeout=5 * 60)
