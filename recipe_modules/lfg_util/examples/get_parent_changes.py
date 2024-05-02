# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing what the changes corresponding to parent commit were."""

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'depot_tools/gerrit',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/time',
    'lfg_util',
]


def RunSteps(api):
  host = 'chromium-review.googlesource.com'
  project = 'kernel'
  changes = [
      GerritChange(change=123456, host=host, project=project, patchset=1)
  ]
  kwargs = {}
  good_parent = {
      'patch_set_number': 2,
      'change_number': 324328,
      'change_id': 'alsdkfjaksdljfljjasdfwdfasdfawefw2134723'
  }
  bad_parent = {}
  kwargs['revisions'] = {
      'asdjfhsdkhfkhk32y23797397': {
          'parents_data': [good_parent, bad_parent]
      }
  }
  gerrit_response_data = api.gerrit.test_api.get_one_change_response_data(
      change_number=123456, patchset=2, **kwargs)
  step_test_data = lambda: gerrit_response_data
  expected_result = [
      GerritChange(change=324328, host=host, project=project, patchset=2)
  ]
  result = api.lfg_util.get_parent_changes(merge_commit_cls=changes,
                                           step_test_data=step_test_data)
  api.assertions.assertEqual(result, expected_result)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )
