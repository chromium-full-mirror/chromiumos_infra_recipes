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
    'recipe_engine/step',
    'easy',
]

PROPERTIES = TastVmProperties

PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'
TAST_ARCHIVE_PATH = 'tast/tast'

def RunSteps(api, properties):
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  with api.step.nest('setup RTD') as step:
    step.text = 'download tast executable'
    server_packages_tar = test_artifacts_dir.join('autotest_server_package.tar')
    tast_dir = test_artifacts_dir.join('tast')
    tast_exec_path = str(tast_dir.join('tast'))
    api.gsutil.download(
        properties.build_payload.artifacts_gs_bucket,
        os.path.join(properties.build_payload.artifacts_gs_path, 'autotest_server_package.tar'),
        server_packages_tar, name='download tast bundle from GS')
    api.archive.extract('unzip tast bundle', server_packages_tar, tast_dir,
                        include_files=[TAST_ARCHIVE_PATH])

  with api.step.nest('download vm image'):
    test_image_zip = test_artifacts_dir.join('image.zip')
    test_image_dir = test_artifacts_dir.join('image')
    vm_image_path = str(test_image_dir.join(VM_IMAGE_NAME))
    private_key_path = str(test_image_dir.join(PRIVATE_KEY_NAME))
    api.gsutil.download(
        properties.build_payload.artifacts_gs_bucket,
        os.path.join(properties.build_payload.artifacts_gs_path, 'image.zip'),
        test_image_zip, name='download image bundle from GS')
    api.archive.extract('unzip image bundle', test_image_zip, test_image_dir,
                        include_files=[VM_IMAGE_NAME, PRIVATE_KEY_NAME])

def GenTests(api):
  yield (api.test('basic'))
