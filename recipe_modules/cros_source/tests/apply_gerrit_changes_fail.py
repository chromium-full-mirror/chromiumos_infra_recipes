# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_source',
    'repo',
    'src_state',
]
from recipe_engine import post_process


def RunSteps(api):
  api.cros_source.apply_gerrit_changes(api.src_state.gerrit_changes)


def GenTests(api):

  yield api.cros_source.test(
      'apply-gerrit-changes-fail',
      api.repo.fail_repo_sync(True),
      api.post_check(post_process.StepFailure,
                     'patch manifest.get patched manifest.retry cache sync'),
  )

  yield api.cros_source.test(
      'apply-gerrit-changes-success',
      api.post_check(post_process.StatusSuccess),
  )
