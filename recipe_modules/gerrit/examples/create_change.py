# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]


def RunSteps(api):
  change = api.gerrit.create_change('project', reviewers=['jeff'], topic='pupr')
  api.assertions.assertEqual(change.host, 'host-review.googlesource.com')
  api.assertions.assertEqual(change.project, 'project')
  api.assertions.assertEqual(change.change, 123)


def GenTests(api):
  yield api.test('basic') + api.gerrit.simulated_create_change(
      'create gerrit change for project',
      'https://host-review.googlesource.com/c/project/+/123')
