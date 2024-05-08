# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_depended_cls function."""

from recipe_engine import post_process
from PB.recipe_modules.chromeos.lfg_util.examples.test import \
  GetDependedClsProperties
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'gerrit',
    'git_footers',
    'lfg_util',
]

PROPERTIES = GetDependedClsProperties

RELATED_OUTPUT = {
    'related': [{
        '_change_number': 456,
        '_revision_number': 1,
        'host': 'test-host',
        'project': 'sample'
    }, {
        '_change_number': 789,
        '_revision_number': 1,
        'host': 'test-host',
        'project': 'sample'
    }]
}


def RunSteps(api, properties):
  example_change = [GerritChange(
      host='test-host',
      change=1234,
      patchset=1,
  )]

  actual = api.lfg_util.get_depended_cls(example_change)

  api.assertions.assertCountEqual(properties.change_ids,
                                  [c.change for c in actual])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(change_ids=[321, 123, 456, 789, 4321]),
      api.git_footers.simulated_get_footers(
          ['chromium:321', 'chromium:123'],
          'check if all Cq-Depend CLs are included'),
      api.gerrit.set_is_merge_commit(1234, 'test-host', True),
      api.step_data(
          'get parent commits of merge CLs.gerrit changes',
          api.json.output([{
              'revisions': {
                  'test-revision-1': {
                      'parents_data': [{
                          'patch_set_number': 1,
                          'change_number': 4321,
                          'change_id': 'test-change-id-1',
                      }]
                  }
              }
          }])),
      api.gerrit.set_gerrit_related_changes(RELATED_OUTPUT,
                                            step_name='find related CLs'),
      api.post_process(post_process.DropExpectation),
  )
