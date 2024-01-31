# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from RECIPE_MODULES.chromeos.gerrit.api import Label

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]



def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=12345678,
      patchset=3,
  )
  gerrit_change_remote = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
      patchset=3,
  )
  labels = {
      Label.CODE_REVIEW: 2,
      Label.VERIFIED: 1,
  }
  ref = api.gerrit.set_change_labels(gerrit_change, labels)
  api.assertions.assertEqual(ref,
                             'HEAD:refs/for/main%l=Code-Review+2,l=Verified+1')

  applied_labels = api.gerrit.set_change_labels_remote(gerrit_change_remote,
                                                       labels)
  api.assertions.assertEqual(applied_labels,
                             '{"labels": {"Code-Review": 2, "Verified": 1}}')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'retry-succeed',
      api.step_data('set labels on CL 12345678.git push', retcode=1),
      api.step_data('set labels on CL 12345678.git push (2)', retcode=1),
      api.post_check(post_process.MustRun,
                     'set labels on CL 12345678.git push (3)'))

  yield api.test(
      'retry-fail',
      api.step_data('set labels on CL 12345678.git push', retcode=1),
      api.step_data('set labels on CL 12345678.git push (2)', retcode=1),
      api.step_data('set labels on CL 12345678.git push (3)', retcode=1),
      api.post_check(post_process.StepException, 'set labels on CL 12345678'),
      status='INFRA_FAILURE',
  )
