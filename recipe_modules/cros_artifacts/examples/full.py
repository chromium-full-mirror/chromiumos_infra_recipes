# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_artifacts',
]

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig


def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'

  api.cros_artifacts.upload_artifacts(target, BuilderConfig.Id.POSTSUBMIT,
                                      'artifacts_gs_bucket',
                                      [BuilderConfig.Artifacts.EBUILD_LOGS],
                                      name='upload ebuild logs')
  api.cros_artifacts.upload_artifacts(target, BuilderConfig.Id.POSTSUBMIT,
                                      'artifacts_gs_bucket',
                                      [BuilderConfig.Artifacts.FIRMWARE],
                                      name='upload firmware archive')
  api.cros_artifacts.upload_artifacts(
      target, BuilderConfig.Id.CQ,
      'artifacts_gs_bucket', [
          BuilderConfig.Artifacts.IMAGE_ZIP,
          BuilderConfig.Artifacts.AUTOTEST_FILES,
          BuilderConfig.Artifacts.TAST_FILES,
          BuilderConfig.Artifacts.PINNED_GUEST_IMAGES,
          BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD,
      ], name='upload test artifacts')


def GenTests(api):
  yield api.test('basic')
