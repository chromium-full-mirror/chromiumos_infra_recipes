# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_artifacts',
]

from PB.chromite.api import sysroot

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig

def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'

  api.cros_artifacts.upload_artifacts(
      'target-postsubmit',
      target, BuilderConfig.Id.POSTSUBMIT, 'artifacts_gs_bucket',
      [BuilderConfig.Artifacts.EBUILD_LOGS],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      name='upload ebuild logs')

  api.cros_artifacts.upload_artifacts(
      'target-postsubmit',
      target, BuilderConfig.Id.POSTSUBMIT, 'artifacts_gs_bucket',
      [BuilderConfig.Artifacts.FIRMWARE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      name='upload firmware archive')

  api.cros_artifacts.upload_artifacts(
      'target-cq',
      target, BuilderConfig.Id.CQ,
      'artifacts_gs_bucket', [
          BuilderConfig.Artifacts.IMAGE_ZIP,
          BuilderConfig.Artifacts.AUTOTEST_FILES,
          BuilderConfig.Artifacts.TAST_FILES,
          BuilderConfig.Artifacts.PINNED_GUEST_IMAGES,
          BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD,
      ],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      name='upload test artifacts')

  api.cros_artifacts.upload_artifacts(
      'target-toolchain',
      target, BuilderConfig.Id.TOOLCHAIN,
      'artifacts_gs_bucket', [
          BuilderConfig.Artifacts.UNVERIFIED_CHROME_LLVM_ORDERFILE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      publish_info=[
          BuilderConfig.Artifacts.PublishInfo(
              publish_gs_location='publish_gs_location',
              acl_name='public-read',
              publish_types=[
                  BuilderConfig.Artifacts.UNVERIFIED_CHROME_LLVM_ORDERFILE]),
          BuilderConfig.Artifacts.PublishInfo(
              publish_gs_location='pub2/%(gs_path)s',
              publish_types=[
                  BuilderConfig.Artifacts.UNVERIFIED_CHROME_LLVM_ORDERFILE])],
  )

def GenTests(api):
  yield api.test('basic')
