# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_artifacts',
]

from PB.chromiumos import common


def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'

  api.cros_artifacts.upload_artifacts('upload ebuild logs', target,
                                      'postsubmit', ['ebuild-logs'])
  api.cros_artifacts.upload_artifacts('upload firmware archive', target,
                                      'postsubmit', ['firmware'])
  api.cros_artifacts.upload_artifacts('upload test artifacts', target,
                                      'cq', [
                                          'autotest-files',
                                          'tast-files',
                                          'pinned-guest-images',
                                          'test-update-payload',
                                      ])


def GenTests(api):
  yield api.test('basic')
