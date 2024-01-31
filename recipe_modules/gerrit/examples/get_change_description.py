# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]



def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  api.assertions.assertEqual(
      api.gerrit.get_change_description(gerrit_change),
      api.gerrit.test_api.test_gerrit_change_description())

  api.assertions.assertEqual(
      api.gerrit.get_change_description(gerrit_change, memoize=True),
      api.gerrit.test_api.test_gerrit_change_description())

  # Do it again, but this time we hit the cache.
  api.assertions.assertEqual(
      api.gerrit.get_change_description(gerrit_change, memoize=True),
      api.gerrit.test_api.test_gerrit_change_description())


def GenTests(api):
  yield api.test('basic')
