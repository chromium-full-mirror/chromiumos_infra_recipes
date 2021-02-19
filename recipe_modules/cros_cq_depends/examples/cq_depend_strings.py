# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'cros_cq_depends',
]


def RunSteps(api):
  gerrit_change = GerritChange(
      host='https://foo-review.googlesource.com',
      project='bar',
      change=123,
      patchset=1,
  )
  another_gerrit_change = GerritChange(
      host='baz-review.googlesource.com',
      change=456,
  )

  api.assertions.assertEqual(
      api.cros_cq_depends.get_cq_depend_reference(gerrit_change),
      'foo:123')

  api.assertions.assertEqual(
      api.cros_cq_depends.get_cq_depend([gerrit_change]),
      'Cq-Depend: foo:123')

  api.assertions.assertEqual(api.cros_cq_depends.get_cq_depend([]), '')

  changes = [gerrit_change, another_gerrit_change]
  actual = api.cros_cq_depends.get_mutual_cq_depend(changes)
  expected = ['Cq-Depend: baz:456', 'Cq-Depend: foo:123']
  api.assertions.assertEqual(actual, expected)


def GenTests(api):
  yield api.test('basic')
