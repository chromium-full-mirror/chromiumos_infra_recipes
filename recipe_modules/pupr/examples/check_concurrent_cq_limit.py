# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
    'pupr',
]


def RunSteps(api):
  # Test with limit <= 0
  limit_exceeded, running_count = api.pupr.check_concurrent_cq_limit([], 0)
  api.assertions.assertFalse(limit_exceeded)
  api.assertions.assertEqual(running_count, 0)

  # Test with limit > 0
  open_changes = [
      common.GerritChange(host='host-review.googlesource.com', change=1,
                          project='project', patchset=1)
  ]
  with api.step.nest('check concurrent CQ runs'):
    open_patch_sets = api.gerrit.fetch_patch_sets(open_changes,
                                                  include_messages=True,
                                                  include_detailed_labels=True)
    limit_exceeded, running_count = api.pupr.check_concurrent_cq_limit(
        open_patch_sets, 1)
  api.assertions.assertTrue(limit_exceeded)
  api.assertions.assertEqual(running_count, 1)
  api.assertions.assertEqual(api.pupr.count_running_cls(open_patch_sets), 1)


def GenTests(api):
  open_changes_list = [
      common.GerritChange(host='host-review.googlesource.com', change=1,
                          project='project', patchset=1)
  ]
  fetch_response_running = {
      1: {
          '_number': 1,
          'project': 'project',
          'patch_set': 1,
          'branch': 'main',
          'created': '2023-01-09 13:11:20.000000000',
          'labels': {
              'Commit-Queue': {
                  'all': [{
                      'value': 1
                  }]
              }
          },
          'messages': [],
      }
  }

  yield api.test(
      'basic',
      api.gerrit.set_gerrit_fetch_changes_response('check concurrent CQ runs',
                                                   open_changes_list,
                                                   fetch_response_running),
  )
