# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running Tast VM tests without Chroot and
    ChromeOS checkout, resulting in much faster tests. The tests will
    use tast executable from build_artifacts.
"""

import os

from google.protobuf import json_format as jsonpb
from PB.recipes.chromeos.tast_vm import TastVmProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'easy',
    'failures',
    'tast_results',
]

PROPERTIES = TastVmProperties

# TODO(dhanyaganesh): Organize all the strings into constants and configs.
PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'
QCOW_IMG_NAME = 'qcow2.img'
TAST_ARCHIVE_PATH = 'tast/tast'
GS_BUCKET = 'chromeos-vmtest-archive'
SYS_LOG_DIR = '/var/log'


def RunSteps(api, properties):
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  with api.step.nest('setup tast') as step:
    step.text = 'download tast executable'
    sp_tar_file = test_artifacts_dir.join('autotest_server_package.tar.bz2')
    archive_path = os.path.join(properties.build_payload.artifacts_gs_path,
                                'autotest_server_package.tar.bz2')
    api.gsutil.download(properties.build_payload.artifacts_gs_bucket,
                        archive_path, sp_tar_file,
                        name='download tast bundle from GS')
    api.step('untar tast',
             ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  image_archive_dir = api.path.mkdtemp(prefix='image-archive')
  with api.step.nest('setup vm'):
    test_image_zip = image_archive_dir.join('image.zip')
    test_image_dir = image_archive_dir.join('image')
    vm_image_path = str(test_image_dir.join(VM_IMAGE_NAME))
    qcow_image_path = str(test_image_dir.join(QCOW_IMG_NAME))
    private_key_path = str(test_image_dir.join(PRIVATE_KEY_NAME))
    api.gsutil.download(
        properties.build_payload.artifacts_gs_bucket,
        os.path.join(properties.build_payload.artifacts_gs_path, 'image.zip'),
        test_image_zip, name='download image bundle from GS')
    api.archive.extract('unzip image bundle', test_image_zip, test_image_dir,
                        include_files=[VM_IMAGE_NAME, PRIVATE_KEY_NAME])

    # Setup qemu debug.
    kvm_pid_file = api.path.mkstemp(prefix='kvm-pid')
    kvm_monitor_file = api.path.mkstemp(prefix='kvm-monitor')
    kvm_monitor_serial_file = api.path.mkstemp(prefix='kvm-monitor-serial')

    api.step('convert image to qcow format', [
        'qemu-img', \
        'create', \
        '-f', 'qcow2', \
        '-b', vm_image_path, \
        qcow_image_path \
    ])
    api.step('launch image as vm', [
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
    ])
    api.step('calibrate ssh key permissions',
             ['chmod', '400', private_key_path])
    api.step('connect via ssh', [
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
    ])

  with api.step.nest('run tast tests'):
    test_results_dir = api.path.mkdtemp(prefix='test-results')
    tast_dir = test_artifacts_dir.join('tast')
    for expr in properties.expressions:
      api.step('tast run', [
          str(tast_dir.join('tast')), \
          '-verbose', \
          'run', \
          '-build=false', \
          '-waituntilready', \
          '-continueafterfailure', \
          '-extrauseflags=tast_vm', \
          '-resultsdir', str(test_results_dir), \
          '-keyfile={}'.format(private_key_path), \
          '-remotebundledir={}'.format(
              str(tast_dir.join('bundles').join('remote'))), \
          '-remotedatadir={}'.format(str(
              tast_dir.join('data'))), \
          '-remoterunner={}'.format(
              str(tast_dir.join('remote_test_runner'))), \
          'localhost:9222', \
          expr
      ], ok_ret='any')
    task_result = api.tast_results.get_results(test_results_dir,
                                               properties.name)
    api.tast_results.archive_results(test_results_dir, GS_BUCKET)
    failures = api.tast_results.get_failures(task_result)
    api.easy.set_property_step('task_result', jsonpb.MessageToDict(task_result))
    api.step('kill vm', ['pkill', '-F', kvm_pid_file])
    api.tast_results.record_logs(SYS_LOG_DIR)
    with api.step.nest('qemu debug') as step:
      step.presentation.logs['kvm.monitor'] = api.file.read_text(
          'reading file', kvm_monitor_file)
      step.presentation.logs['kvm.monitor.serial'] = api.file.read_text(
          'reading file', kvm_monitor_serial_file)

  api.tast_results.print_results(task_result, test_results_dir)

  return api.failures.aggregate_failures(failures)


def GenTests(api):
  yield (api.test('basic') + api.properties(expressions=['expr']))
