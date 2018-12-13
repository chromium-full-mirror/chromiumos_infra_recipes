# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'changes',
]


def RunSteps(api):
  change = api.changes.get_changes()[0]
  assert change.project == 'chromium/src'
  assert change.branch == 'master'
  assert change.subject == 'Change title'
  assert change.git_fetch_url == 'https://chromium.googlesource.com/chromium/src'
  assert change.git_fetch_ref == 'refs/changes/27/91827/1'
  assert change.subject == 'Change title'
  assert change.view_url == 'https://chromium-review.googlesource.com/91827'


def GenTests(api):
  yield (api.test('basic') +  #
         api.changes.buildbucket_gerrit_change())
  yield (api.test('bad patchset') +  #
         api.changes.buildbucket_gerrit_change(patch_set=9) +
         api.expect_exception('ValueError'))
