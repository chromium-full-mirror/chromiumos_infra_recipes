# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'gerrit',
]


def RunSteps(api):
  change = common_pb2.GerritChange()
  change.host = 'chromium-review.googlesource.com'
  change.change = 91827
  change.patchset = 1
  patch = api.gerrit.fetch_patch_sets([change])[0]
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
  api.gerrit.changes_are_submittable([change])
  api.gerrit.changes_are_submittable([change],
      test_output_data=api.gerrit.test_api.test_changes_are_submittable(
          errors=['could not cherry pick']))
  api.gerrit.test_api.simulated_changes_are_submittable(submittable=False)

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
  api.gerrit.test_api.test_gerrit_change_url()
  api.gerrit.test_api.test_changes_are_submittable()

  # Parse full gerrit change URL.
  gerrit_change_url = (
      'https://chromium-review.googlesource.com/c/'
      'chromiumos/chromite/+/12345/6')
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host,
                             'chromium-review.googlesource.com')
  api.assertions.assertEqual(gerrit_change.project, 'chromiumos/chromite')
  api.assertions.assertEqual(gerrit_change.change, 12345)
  api.assertions.assertEqual(gerrit_change.patchset, 6)

  # Parse full gerrit change URL without patchset.
  gerrit_change_url = (
      'https://chrome-internal-review.googlesource.com/c/'
      'chromeos/infra/config/+/12345')
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host,
                             'chrome-internal-review.googlesource.com')
  api.assertions.assertEqual(gerrit_change.project, 'chromeos/infra/config')
  api.assertions.assertEqual(gerrit_change.change, 12345)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse full gerrit change URL without https://
  gerrit_change_url = (
      'chrome-internal-review.googlesource.com/c/'
      'chromeos/infra/config/+/12345')
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host,
                             'chrome-internal-review.googlesource.com')
  api.assertions.assertEqual(gerrit_change.project, 'chromeos/infra/config')
  api.assertions.assertEqual(gerrit_change.change, 12345)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse dumb gerrit change URL.
  gerrit_change_url = 'https://chrome-internal-review.googlesource.com/12345'
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host,
                             'chrome-internal-review.googlesource.com')
  api.assertions.assertEqual(gerrit_change.change, 12345)
  api.assertions.assertFalse(gerrit_change.project)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse dumb gerrit change URL without https://
  gerrit_change_url = 'chrome-internal-review.googlesource.com/12345'
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host,
                             'chrome-internal-review.googlesource.com')
  api.assertions.assertEqual(gerrit_change.change, 12345)
  api.assertions.assertFalse(gerrit_change.project)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse URL as seen from coreboot full style.
  gerrit_change_url = 'https://review.coreboot.org/c/em100/+/30938/3'
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host, 'review.coreboot.org')
  api.assertions.assertEqual(gerrit_change.project, 'em100')
  api.assertions.assertEqual(gerrit_change.change, 30938)
  api.assertions.assertEqual(gerrit_change.patchset, 3)

  # Parse URL as seen from coreboot full style sans the patchset.
  gerrit_change_url = 'https://review.coreboot.org/c/em100/+/30938'
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host, 'review.coreboot.org')
  api.assertions.assertEqual(gerrit_change.project, 'em100')
  api.assertions.assertEqual(gerrit_change.change, 30938)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse URL as seen from coreboot abbreviated style.
  gerrit_change_url = 'https://review.coreboot.org/c/30938'
  gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host, 'review.coreboot.org')
  api.assertions.assertEqual(gerrit_change.change, 30938)
  api.assertions.assertFalse(gerrit_change.project)
  api.assertions.assertFalse(gerrit_change.patchset)

  # Parse URL from smart gerrit change.
  gerrit_change = common_pb2.GerritChange(
      host='chromium-review.googlesource.com',
      project='chromiumos/chromite', change=123, patchset=4)
  gerrit_change_url = api.gerrit.parse_gerrit_change_url(gerrit_change)
  api.assertions.assertEqual(
      gerrit_change_url,
      'https://chromium-review.googlesource.com/c/chromiumos/chromite/+/123/4')

  # Parse URL from dumb gerrit change.
  gerrit_change = common_pb2.GerritChange(
      host='chromium-review.googlesource.com', change=12345)
  gerrit_change_url = api.gerrit.parse_gerrit_change_url(gerrit_change)
  api.assertions.assertEqual(gerrit_change_url,
                             'https://chromium-review.googlesource.com/12345')

  # Test has_chromite_changes
  gerrit_change = common_pb2.GerritChange(
      project='chromiumos/chromite', host='crrev.com', patchset=42, change=1)
  api.assertions.assertTrue(api.gerrit.has_chromite_changes([gerrit_change]))
  gerrit_change.project = 'something_else'
  api.assertions.assertFalse(api.gerrit.has_chromite_changes([gerrit_change]))
  api.assertions.assertFalse(api.gerrit.has_chromite_changes([]))


def GenTests(api):
  yield api.test('basic')
