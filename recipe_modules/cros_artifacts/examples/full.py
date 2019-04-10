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

  api.cros_artifacts.upload_artifacts('upload ebuild logs', target,
                                      'postsubmit',
                                      [BuilderConfig.Artifacts.EBUILD_LOGS])
  api.cros_artifacts.upload_artifacts('upload firmware archive', target,
                                      'postsubmit',
                                      [BuilderConfig.Artifacts.FIRMWARE])
  api.cros_artifacts.upload_artifacts('upload test artifacts', target, 'cq', [
      BuilderConfig.Artifacts.IMAGE_ZIP,
      BuilderConfig.Artifacts.AUTOTEST_FILES,
      BuilderConfig.Artifacts.TAST_FILES,
      BuilderConfig.Artifacts.PINNED_GUEST_IMAGES,
      BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD,
  ])


def GenTests(api):
  yield api.test('basic')
