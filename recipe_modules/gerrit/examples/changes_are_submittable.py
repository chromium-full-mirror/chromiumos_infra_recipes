# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  # TODO(evanhernandez): Need to normalize how we handle test data.
  change = GerritChange(
      host='chromium-review.googlesource.com',
      change=91827,
      patchset=1,
  )

  api.assertions.assertTrue(api.gerrit.changes_submittable([change]))
  api.assertions.assertFalse(api.gerrit.changes_submittable([change]))


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.simulated_changes_are_submittable(submittable=False,
                                                   iteration=2))
