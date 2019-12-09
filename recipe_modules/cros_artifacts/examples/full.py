# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_artifacts',
    'recipe_engine/file',
]

from PB.chromite.api import sysroot

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig


def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'

  # An artifact with a prepare service.
  api.cros_artifacts.prepare_for_build(
      [BuilderConfig.Artifacts.VERIFIED_ORDERING_FILE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
  )

  # An artifact with no prepare service.
  api.cros_artifacts.prepare_for_build(
      [BuilderConfig.Artifacts.IMAGE_ZIP],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
  )

  api.cros_artifacts.upload_artifacts(
      target, BuilderConfig.Id.POSTSUBMIT, 'artifacts_gs_bucket',
      [BuilderConfig.Artifacts.EBUILD_LOGS],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
                                      name='upload ebuild logs')

  api.cros_artifacts.upload_artifacts(
      target, BuilderConfig.Id.POSTSUBMIT, 'artifacts_gs_bucket',
      [BuilderConfig.Artifacts.FIRMWARE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      name='upload firmware archive')

  api.cros_artifacts.upload_artifacts(
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
      target, BuilderConfig.Id.TOOLCHAIN,
      'artifacts_gs_bucket', [BuilderConfig.Artifacts.UNVERIFIED_ORDERING_FILE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      publish_info=[
          BuilderConfig.Artifacts.PublishInfo(
              publish_gs_bucket='publish_gs_bucket',
              publish_types=[
                  BuilderConfig.Artifacts.UNVERIFIED_ORDERING_FILE])])

def GenTests(api):
  yield api.test('basic')

  # Test POINTLESS and NEEDED.  UNKNOWN is handled by 'basic' above, since it is
  # the default response found in test_api.py
  yield (api.test('pointless') + api.step_data(
      'prepare artifacts.call chromite.api.ToolchainService/'
      'PrepareForBuild.read output file',
      api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield (api.test('needed') + api.step_data(
      'prepare artifacts.call chromite.api.ToolchainService/'
      'PrepareForBuild.read output file',
      api.file.read_raw(content='{"build_relevance": "NEEDED"}')))
