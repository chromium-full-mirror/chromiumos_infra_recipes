# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from google.protobuf import json_format as jsonpb
from recipe_engine.recipe_api import RecipeApi, StepFailure
from RECIPE_MODULES.chromeos.util.util import exponential_retry
from PB.test_platform.taskstate import TaskState

SYS_LOG_DIR = '/var/log'
VM_ARTIFACT_TARBALL = '/tmp/artifacts.tar'
ARTIFACT_TARBALL_NAME = 'artifacts.tar'
VM_ARTIFACT_LIST = ['/var/log', '/var/spool/crash']
PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'
QCOW_IMG_NAME = 'qcow2.img'


class TastExecApi(RecipeApi):
  """A module to execute tast commands."""

  def __init__(self, properties, *args, **kwargs):
    super(TastExecApi, self).__init__(*args, **kwargs)
    self._exec_timeout = properties.exec_timeout or 90 * 60
    self._should_retry = properties.should_retry
    self._public_builder = properties.public_builder

  def download_tast(self, artifacts_gs_bucket, artifacts_gs_path,
                    test_artifacts_dir):
    """Downloads the tast executable from specified build artifacts.

    Args:
      artifacts_gs_bucket (str): The bucket containing build artifacts.
      artifacts_gs_path (str): The bucket path containing the build output,
        for example, "eve-paladin/R78-11588.0.0".
      test_artifacts_dir (str): The directory to which files should be
        downloaded. The tast executable will be found at tast/tast relative
        to this directory.
    """
    with self.m.step.nest('setup tast') as presentation:
      presentation.text = 'download tast executable'
      sp_tar_file = test_artifacts_dir.join('autotest_server_package.tar.bz2')
      archive_path = os.path.join(artifacts_gs_path,
                                  'autotest_server_package.tar.bz2')
      self.m.gsutil.download(artifacts_gs_bucket, archive_path, sp_tar_file,
                             name='download tast bundle from GS')
      self.m.step(
          'untar tast',
          ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  def download_vm(self, artifacts_gs_bucket, artifacts_gs_path, vm_dir):
    """Downloads the VM image from specified build artifacts.

    Args:
      artifacts_gs_bucket (str): The bucket containing build artifacts.
      artifacts_gs_path (str): The bucket path containing the build output,
        for example, "eve-paladin/R78-11588.0.0".
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
      self.m.gsutil.download(artifacts_gs_bucket,
                             os.path.join(artifacts_gs_path,
                                          'image.zip'), test_image_zip,
                             name='download image bundle from GS')
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

  def run_vm(self, suite_name, expressions, qcow_image_path, test_artifacts_dir,
             private_key_path, artifacts_gs_bucket, artifacts_gs_path):
    """Run tast tests in a VM with one retry and upload logs to Google storage.

    Args:
      suite_name (str): Name of the suite to run.
      expressions (list[str]): Expressions to test.
      qcow_image_path (Path): Path to image in qcow format.
      test_artifacts_dir (Path): Dir containing test artifacts.
      private_key_path (Path): Path to private key.
      artifacts_gs_bucket (str): The bucket containing build artifacts.
      artifacts_gs_path (str): The bucket path containing the build output,
        for example, "eve-paladin/R78-11588.0.0".

    Returns:
      A tuple of list(Failures) and a bool indicating whether
        the results were empty.
    """
    # Setup qemu debug.
    task_result = self._retry_iter(suite_name, expressions, qcow_image_path,
                                   test_artifacts_dir, private_key_path,
                                   'first', artifacts_gs_bucket,
                                   artifacts_gs_path)
    tests_to_retry, _ = self.m.tast_results.get_tests_to_retry(task_result)
    all_test_cases = []
    if task_result.test_cases:
      all_test_cases = jsonpb.MessageToDict(task_result)['testCases']
    failures, failed_test_cases = self.m.tast_results.get_failures(
        task_result, tests_to_retry)
    empty_result = task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
    if tests_to_retry and self._should_retry:
      retry_task_result = self._retry_iter(suite_name, tests_to_retry,
                                           qcow_image_path, test_artifacts_dir,
                                           private_key_path, 'second',
                                           artifacts_gs_bucket,
                                           artifacts_gs_path)
      all_test_cases += jsonpb.MessageToDict(retry_task_result)['testCases']
      retry_failures, retry_tcs = self.m.tast_results.get_failures(
          retry_task_result)
      empty_result = \
          retry_task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      failures += retry_failures
      failed_test_cases += retry_tcs

    self.m.easy.set_properties_step(all_test_cases=all_test_cases,
                                    failed_test_cases=failed_test_cases)
    self.m.tast_results.record_logs(SYS_LOG_DIR)

    return failures, empty_result

  def _retry_iter(self, suite_name, expressions, qcow_image_path,
                  test_artifacts_dir, private_key_path, tag,
                  artifacts_gs_bucket, artifacts_gs_path):
    with self.m.step.nest('%s tast iteration' % tag):
      test_results_dir = self.m.path.mkdtemp(prefix='test-results')
      tests = self.run_direct_vm(expressions, qcow_image_path,
                                 test_artifacts_dir, private_key_path,
                                 artifacts_gs_bucket, artifacts_gs_path,
                                 test_results_dir)
      return self.m.tast_results.get_results(test_results_dir, suite_name, tag,
                                             tests)

  def run_direct_vm(self, expressions, qcow_image_path, test_artifacts_dir,
                    private_key_path, artifacts_gs_bucket, artifacts_gs_path,
                    test_results_dir, run_args=None):
    """Run tast tests in a VM without retries or results processing.

    Args:
      expressions (list[str]): Expressions describing tests to run.
      qcow_image_path (Path): Path to image in qcow format.
      test_artifacts_dir (Path): Dir containing test artifacts.
      private_key_path (Path): Path to private key.
      artifacts_gs_bucket (str): The bucket containing build artifacts.
      artifacts_gs_path (str): The bucket path containing the build output,
        for example, "eve-paladin/R78-11588.0.0".
      test_results_dir (Path): Path to store tast results.
      run_args (list[str]): Additional arguments to pass to tast (optional).

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    if run_args is None:
      run_args = []

    kvm_pid_file = self.m.path.mkstemp(prefix='kvm-pid')
    kvm_monitor_file = self.m.path.mkstemp(prefix='kvm-monitor')
    kvm_monitor_serial_file = self.m.path.mkstemp(prefix='kvm-monitor-serial')

    self._launch_vm(qcow_image_path, kvm_pid_file, kvm_monitor_file,
                    kvm_monitor_serial_file, private_key_path)
    try:
      tests = self.run_direct('localhost:9222', expressions, test_artifacts_dir,
                              artifacts_gs_bucket, artifacts_gs_path,
                              test_results_dir,
                              private_key_path=private_key_path,
                              run_args=run_args)

      # Add logs and other artifacts from DUT into the test results directory.
      self._archive_vm_artifacts(private_key_path, test_results_dir)
    finally:
      # Always kill QEMU.
      self._kill_vm(kvm_pid_file)
    self._record_qemu_logs(kvm_monitor_file, kvm_monitor_serial_file)
    return tests

  def run_direct(self, dut_name, expressions, test_artifacts_dir,
                 artifacts_gs_bucket, artifacts_gs_path, test_results_dir,
                 private_key_path=None, run_args=None):
    """Run tast tests without retries or results processing.

    Args:
      dut_name (str): The identity of the DUT to connect to,
        for example, my-dut-host-name or localhost:9222 (if testing a VM).
      expressions (list[str]): Expressions describing tests to run.
      test_artifacts_dir (Path): Dir containing test artifacts.
      artifacts_gs_bucket (str): The bucket containing build artifacts.
      artifacts_gs_path (str): The bucket path containing the build output,
        for example, "eve-paladin/R78-11588.0.0".
      test_results_dir (Path): Path to store tast results.
      private_key_path (Path): Path to private key to use (optional).
      run_args (list[str]): Additional arguments to pass to tast (optional).

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    # Used by tast to determine where to download private bundles.
    build_artifacts_url = 'gs://{}/{}/'.format(artifacts_gs_bucket,
                                               artifacts_gs_path)
    tast_dir = test_artifacts_dir.join('tast')
    tests = self._list_tests(dut_name, expressions, tast_dir, private_key_path,
                             build_artifacts_url)
    self._run_tests(dut_name, expressions, tast_dir, private_key_path,
                    build_artifacts_url, test_results_dir, run_args)
    return tests

  @exponential_retry(retries=2)
  def _archive_vm_artifacts(self, private_key_path, output_dir):
    self.m.step('gather artifacts on VM', [
        'ssh', \
        '-p', '9222', \
        '-oConnectionAttempts=4', \
        '-oUserKnownHostsFile=/dev/null', \
        '-oProtocol=2', \
        '-oConnectTimeout=30', \
        '-oServerAliveCountMax=8', \
        '-oStrictHostKeyChecking=no', \
        '-oServerAliveInterval=15', \
        '-oNumberOfPasswordPrompts=0', \
        '-oIdentitiesOnly=yes', \
        '-i', private_key_path, \
        'root@localhost', '--', 'tar', 'cf', VM_ARTIFACT_TARBALL] +
        VM_ARTIFACT_LIST,
        infra_step=True, timeout=5*60)
    self.m.step('download artifacts from VM', [
        'scp', \
        '-P', '9222', \
        '-oConnectionAttempts=4', \
        '-oUserKnownHostsFile=/dev/null', \
        '-oProtocol=2', \
        '-oConnectTimeout=30', \
        '-oServerAliveCountMax=8', \
        '-oStrictHostKeyChecking=no', \
        '-oServerAliveInterval=15', \
        '-oNumberOfPasswordPrompts=0', \
        '-oIdentitiesOnly=yes', \
        '-i', private_key_path, \
        'root@localhost:%s'%VM_ARTIFACT_TARBALL, str(output_dir.join(ARTIFACT_TARBALL_NAME))],
        infra_step=True, timeout=5*60)

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
    list(expressions), timeout=2 * 60)

    tests = [t.strip() for t in list_stdout.splitlines()]
    return tests

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
        '-netdev', 'user,id=eth0,net=10.0.2.0/27,hostfwd=tcp:127.0.0.1:9222-:22', \
        '-enable-kvm', \
        '-display', 'none'
    ], infra_step=True)
    try:
      self._test_ssh_conn(private_key_path)
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

  @exponential_retry(retries=3)
  def _test_ssh_conn(self, private_key_path):
    self.m.step('connect via ssh', [
        'ssh', \
        '-p', '9222', \
        '-oConnectionAttempts=4', \
        '-oUserKnownHostsFile=/dev/null', \
        '-oProtocol=2', \
        '-oConnectTimeout=30', \
        '-oServerAliveCountMax=8', \
        '-oStrictHostKeyChecking=no', \
        '-oServerAliveInterval=15', \
        '-oNumberOfPasswordPrompts=0', \
        '-oIdentitiesOnly=yes', \
        '-i', private_key_path, \
        'root@localhost', '--', 'true'
    ], infra_step=True, timeout=5*60)
