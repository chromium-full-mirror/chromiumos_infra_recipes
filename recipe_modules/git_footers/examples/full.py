# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test git_footers calls."""

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'git_footers',
]


DESCRIPTION_EXISTING = '''
This is a change where the footer in question already exists.

BUG=None
TEST=None

Cq-Footer: foo
Cq-Depend: {}
Change-Id: ffffffffffffffff
'''

DESCRIPTION_NON_EXISTING = '''
This is a change where the footer in question does not exist.

BUG=None
TEST=None
{}
Cq-Footer: foo
Change-Id: ffffffffffffffff
'''


def RunSteps(api):
  gerrit_change_a = GerritChange(
      host='chromium-review.googlesource.com',
      change=91827,
      patchset=1,
  )
  gerrit_change_b = GerritChange(
      host='chromium-review.googlesource.com',
      change=91827,
      patchset=1,
  )
  gerrit_changes = [gerrit_change_a, gerrit_change_b]

  api.assertions.assertEqual(
      api.git_footers.from_ref('HEAD', key='Reviewed-On'), ['HEAD:Reviewed-On'])
  api.assertions.assertEqual(
      api.git_footers.from_message('message', key='key'), ['message:key'])
  api.git_footers.position_num('HEAD')
  api.git_footers.from_gerrit_change(gerrit_change_a)

  if api.properties['invalid_cr_commit_position']:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 1)
  else:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 101)
    api.assertions.assertEqual(
        api.git_footers.position_ref('HEAD'), 'refs/heads/main')

  api.assertions.assertTrue(api.git_footers.test_api.step_data('foo', 'bar'))
  api.assertions.assertTrue(
      api.git_footers.test_api.simulated_get_footers(['footer1', 'footer2']))
  api.assertions.assertTrue(
      api.git_footers.test_api.simulated_get_footers(['footer1', 'footer2'],
                                                     parent_step_name='test',
                                                     step_number=2))

  description_existing = DESCRIPTION_EXISTING.format('bar')
  expected_description = DESCRIPTION_EXISTING.format('baz')
  api.assertions.assertEqual(
      api.git_footers.edit_add_change_description(description_existing,
                                                  'Cq-Depend', 'baz'),
      expected_description)

  description_existing = DESCRIPTION_EXISTING.format('bar')
  expected_description = DESCRIPTION_EXISTING.format('baz')
  api.assertions.assertEqual(
      api.git_footers.edit_add_change_description(description_existing,
                                                  'Cq-Depend',
                                                  'Cq-Depend: baz'),
      expected_description)

  description_nonexisting = DESCRIPTION_NON_EXISTING.format('')
  expected_description = DESCRIPTION_NON_EXISTING.format('\nCq-Depend: baz')
  api.assertions.assertEqual(
      api.git_footers.edit_add_change_description(description_nonexisting,
                                                  'Cq-Depend', 'baz'),
      expected_description)
  api.assertions.assertEqual(
      {'deadbeef'},
      api.git_footers.get_footer_values(
          gerrit_changes, 'Change-Id',
          step_test_data=api.git_footers.test_api.step_test_data_factory(
              'deadbeef')))


def GenTests(api):
  yield api.test('basic', api.properties(invalid_cr_commit_position=False))

  yield api.test(
      'bad-cr-commit-position',
      api.properties(invalid_cr_commit_position=True),
      api.step_data('read git footers (5)', retcode=1),
  )
