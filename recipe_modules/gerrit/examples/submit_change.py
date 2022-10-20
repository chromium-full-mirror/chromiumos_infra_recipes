# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  # Difficult to assert on, so just call the function.
  api.gerrit.submit_change(gerrit_change, retries=1)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'retry-succeed', api.step_data('submit CL 123.git_cl land', retcode=1),
      api.post_check(post_process.MustRun, 'submit CL 123.git_cl land (2)'))

  yield api.test('retry-fail',
                 api.step_data('submit CL 123.git_cl land', retcode=1),
                 api.step_data('submit CL 123.git_cl land (2)', retcode=1),
                 api.post_check(post_process.StepFailure, 'submit CL 123'))
