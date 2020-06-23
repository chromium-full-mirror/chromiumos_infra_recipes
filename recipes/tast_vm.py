# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running Tast VM tests without Chroot and
    ChromeOS checkout, resulting in much faster tests. The tests will
    use tast executable from build_artifacts.
"""

import os

from PB.recipes.chromeos.tast_vm import TastVmProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
    'tast_exec',
    'tast_results',
]

PROPERTIES = TastVmProperties

# TODO(dhanyaganesh): Organize all the strings into constants and configs.
PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'
QCOW_IMG_NAME = 'qcow2.img'
TAST_ARCHIVE_PATH = 'tast/tast'
SYS_LOG_DIR = '/var/log'


def RunSteps(api, properties):
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  with api.step.nest('setup tast') as presentation:
    presentation.text = 'download tast executable'
    sp_tar_file = test_artifacts_dir.join('autotest_server_package.tar.bz2')
    archive_path = os.path.join(properties.build_payload.artifacts_gs_path,
                                'autotest_server_package.tar.bz2')
    api.gsutil.download(properties.build_payload.artifacts_gs_bucket,
                        archive_path, sp_tar_file,
                        name='download tast bundle from GS')
    api.step('untar tast',
             ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  image_archive_dir = api.path.mkdtemp(prefix='image-archive')
  with api.step.nest('setup vm image'):
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

    api.step('convert image to qcow format', [
        'qemu-img', \
        'create', \
        '-f', 'qcow2', \
        '-b', vm_image_path, \
        qcow_image_path \
    ])
    api.step('calibrate ssh key permissions',
             ['chmod', '400', private_key_path])

  with api.step.nest('run tast tests'):
    failures, empty_result = api.tast_exec.run(properties.name,
                                               properties.expressions,
                                               qcow_image_path,
                                               test_artifacts_dir,
                                               private_key_path)

  api.tast_results.print_results(failures, empty_result)

  return api.failures.aggregate_failures(failures)

def GenTests(api):
  yield api.test('basic', api.properties(expressions=['expr']))
