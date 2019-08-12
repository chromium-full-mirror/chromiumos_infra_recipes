# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
]

def RunSteps(api):
  # TODO(evanhernandez): These tests could use some work.
  change = GerritChange(
      host='chromium-review.googlesource.com',
      change=91827,
      patchset=1,
  )

  patches = api.gerrit.fetch_patch_sets([change])
  api.assertions.assertEqual(len(patches), 1)

  patch = patches[0]
  api.assertions.assertEqual(patch.project, 'chromium/src')
  api.assertions.assertEqual(patch.branch, 'master')
  api.assertions.assertEqual(patch.subject, 'Change title')
  api.assertions.assertEqual(patch.git_fetch_url,
                             'https://chromium.googlesource.com/chromium/src')
  api.assertions.assertEqual(patch.git_fetch_ref, 'refs/changes/27/91827/1')
  api.assertions.assertEqual(patch.subject, 'Change title')
  api.assertions.assertEqual(patch.short_host, 'chromium')
  api.assertions.assertEqual(patch.display_id, 'chromium:91827')
  api.assertions.assertEqual(patch.display_url,
                             'https://chromium-review.googlesource.com/91827')
  api.assertions.assertIn('my/fake/file', patch.file_infos)

  # Missing FetchInfo.
  del patch._rev_info['fetch']
  api.assertions.assertEqual(
      patch.git_fetch_url,
      'https://chromium-review.googlesource.com/chromium/src')
  api.assertions.assertEqual(patch.git_fetch_ref, 'refs/changes/27/91827/1')

  # Missing result
  try:
    api.gerrit.fetch_patch_sets([change], test_output_data={'changes': [{}]})
  except api.step.StepFailure:
    pass

  api.gerrit.test_api.test_patch_set()


def GenTests(api):
  yield api.test('basic')
