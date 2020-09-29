# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format as jsonpb
from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.util import exponential_retry
from PB.test_platform.taskstate import TaskState

SYS_LOG_DIR = '/var/log'


class TastExecApi(RecipeApi):
  """A module to execute tast commands."""

  def run(self, suite_name, expressions, qcow_image_path, test_artifacts_dir,
          private_key_path):
    """Run tast tests.

    Args:
        suite_name(str): Name of the suite to run.
        expressions(list(str)): Expressions to test.
        qcow_image_path(Path): Path to image in qcow format.
        test_artifacts_dir(Path): Dir containing test artifacts.
        private_key_path(Path): Path to private key.

    Returns:
        A tuple of list(Failures) and a bool indicating whether
        the results were empty.
    """
    # Setup qemu debug.
    task_result = self._tast_iter(suite_name, expressions, qcow_image_path,
                                  test_artifacts_dir, private_key_path, 'first')
    tests_to_retry, _ = self.m.tast_results.get_tests_to_retry(task_result)
    all_test_cases = []
    if task_result.test_cases:
      all_test_cases = jsonpb.MessageToDict(task_result)['testCases']
    failures, failed_test_cases = self.m.tast_results.get_failures(
        task_result, tests_to_retry)
    empty_result = task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
    if tests_to_retry:
      retry_task_result = self._tast_iter(suite_name, tests_to_retry,
                                          qcow_image_path, test_artifacts_dir,
                                          private_key_path, 'second')
      all_test_cases += jsonpb.MessageToDict(retry_task_result)['testCases']
      retry_failures, retry_tcs = self.m.tast_results.get_failures(
          retry_task_result)
      empty_result = retry_task_result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      failures += retry_failures
      failed_test_cases += retry_tcs

    self.m.easy.set_properties_step(all_test_cases=all_test_cases,
                                    failed_test_cases=failed_test_cases)
    self.m.tast_results.record_logs(SYS_LOG_DIR)

    return failures, empty_result

  def _tast_iter(self, suite_name, expressions, qcow_image_path,
                 test_artifacts_dir, private_key_path, tag):
    kvm_pid_file = self.m.path.mkstemp(prefix='kvm-pid')
    kvm_monitor_file = self.m.path.mkstemp(prefix='kvm-monitor')
    kvm_monitor_serial_file = self.m.path.mkstemp(prefix='kvm-monitor-serial')

    self._launch_vm(qcow_image_path, kvm_pid_file, kvm_monitor_file,
                    kvm_monitor_serial_file, private_key_path)
    tast_dir = test_artifacts_dir.join('tast')
    task_result = self._run_tast(expressions, tast_dir, private_key_path,
                                 suite_name, tag)

    self._kill_vm(kvm_pid_file)
    self._record_qemu_logs(kvm_monitor_file, kvm_monitor_serial_file)
    return task_result

  def _run_tast(self, expressions, tast_dir, private_key_path, name, tag):
    test_results_dir = self.m.path.mkdtemp(prefix='test-results')
    list_stdout = self.m.easy.stdout_step('tast list', [
        str(tast_dir.join('tast')), \
        'list', \
        '-build=false', \
        '-keyfile={}'.format(private_key_path), \
        '-remotebundledir={}'.format(
            str(tast_dir.join('bundles').join('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir.join('data'))), \
        '-remoterunner={}'.format(
            str(tast_dir.join('remote_test_runner'))), \
        'localhost:9222'] + \
        list(expressions), ok_ret='any', timeout=2 * 60)

    tests = [t.strip() for t in list_stdout.splitlines()]
    self.m.step('tast run %s' % tag, [
        str(tast_dir.join('tast')), \
        '-verbose', \
        'run', \
        '-build=false', \
        '-waituntilready', \
        '-continueafterfailure', \
        '-extrauseflags=tast_vm', \
        '-defaultvarsdir={}'.format(str(tast_dir.join('vars'))), \
        '-resultsdir', str(test_results_dir), \
        '-keyfile={}'.format(private_key_path), \
        '-remotebundledir={}'.format(
            str(tast_dir.join('bundles').join('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir.join('data'))), \
        '-remoterunner={}'.format(
            str(tast_dir.join('remote_test_runner'))), \
        'localhost:9222'] + \
        list(expressions), ok_ret='any', timeout=45 * 60)
    return self.m.tast_results.get_results(test_results_dir, name, tag, tests)

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
