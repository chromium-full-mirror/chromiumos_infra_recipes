# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'gerrit',
]


def RunSteps(api):
  change = api.buildbucket.common_pb2.GerritChange()
  change.host = 'chromium-review.googlesource.com'
  change.change = 91827
  change.patchset = 1
  patch = api.gerrit.fetch_patch_sets([change])[0]
  assert_equal(patch.project, 'chromium/src')
  assert_equal(patch.branch, 'master')
  assert_equal(patch.subject, 'Change title')
  assert_equal(patch.git_fetch_url, 'https://chromium.googlesource.com/chromium/src')
  assert_equal(patch.git_fetch_ref, 'refs/changes/27/91827/1')
  assert_equal(patch.subject, 'Change title')
  assert_equal(patch.short_host, 'chromium')
  assert_equal(patch.display_id, 'chromium:91827')
  assert_equal(patch.display_url, 'https://chromium-review.googlesource.com/91827')

  # Missing FetchInfo.
  del patch._rev_info['fetch']
  assert_equal(patch.git_fetch_url, 'https://chromium-review.googlesource.com/chromium/src')
  assert_equal(patch.git_fetch_ref, 'refs/changes/27/91827/1')

  # Missing result
  api.gerrit.fetch_patch_sets([change], test_output_data={'changes': [{}]})

  api.gerrit.test_api.test_patch_set()


def assert_equal(got, want):
  """Asserts that the two values are equal, or throws AssertionError."""
  assert got == want, '%r != %r' % (got, want)


def GenTests(api):
  yield api.test('basic')
