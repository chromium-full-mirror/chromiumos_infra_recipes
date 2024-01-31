# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from collections import OrderedDict
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_source',
    'src_state',
]



def RunSteps(api):
  all_related_changes = api.properties.thaw()['all_related_changes']
  expected_related_changes_to_apply = api.properties.thaw(
  )['expected_related_changes_to_apply']

  related_changes_to_apply = api.cros_source.related_changes_to_apply(
      api.src_state.gerrit_changes, all_related_changes)
  api.assertions.assertEqual(expected_related_changes_to_apply,
                             related_changes_to_apply)


def GenTests(api):
  MANIFEST_BRANCH = 'snapshot'

  yield api.cros_source.test(
      'no-related', MANIFEST_BRANCH,
      api.properties(all_related_changes={},
                     expected_related_changes_to_apply={}),
      api.post_process(post_process.DropExpectation))

  ALL_RELATED_CHANGES = {
      '123456': [{
          '_change_number': '666',
          '_revision_number': '7',
          'project': 'dont/include'
      }, {
          '_change_number': '123456',
          '_revision_number': '7',
          'project': 'chromeos/manifest-internal'
      }]
  }

  yield api.cros_source.test(
      'only-first-in-stack', MANIFEST_BRANCH,
      api.properties(all_related_changes=ALL_RELATED_CHANGES,
                     expected_related_changes_to_apply={}),
      api.post_process(post_process.DropExpectation))

  ALL_RELATED_CHANGES_WITH_DUPE = {
      '123456': [{
          '_change_number': '666',
          '_revision_number': '7',
          'project': 'dont/include'
      }, {
          '_change_number': '123456',
          '_revision_number': '7',
          'project': 'chromeos/manifest-internal'
      }, {
          '_change_number': '123',
          '_revision_number': '1',
          'project': 'should/include'
      }, {
          '_change_number': '123',
          '_revision_number': '1',
          'project': 'should/include'
      }]
  }

  EXPECTED_RELATED_CHANGES_TO_APPLY = OrderedDict({
      '123456': [{
          '_change_number': '123',
          '_revision_number': '1',
          'project': 'should/include'
      }]
  })

  yield api.cros_source.test(
      'remove-dupe', MANIFEST_BRANCH,
      api.properties(
          all_related_changes=ALL_RELATED_CHANGES_WITH_DUPE,
          expected_related_changes_to_apply=EXPECTED_RELATED_CHANGES_TO_APPLY),
      api.post_process(post_process.DropExpectation))
