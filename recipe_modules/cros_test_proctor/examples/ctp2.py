# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'cros_test_proctor',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  gerrit_changes = [
      GerritChange(
          host="chromium-review.googlesource.com",
          project="src/projectA",
          change=123,
          patchset=3,
      ),
      GerritChange(
          host="chromium-review.googlesource.com",
          project="src/projectB",
          change=456,
          patchset=7,
      ),
  ]

  with api.assertions.assertRaisesRegexp(ValueError, 'CTP2 not implemented'):
    api.cros_test_proctor.run_proctor_v2(gerrit_changes)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'no-starlark-files',
      api.step_data(
          'run tests.schedule tests.find relevant plans.list output files',
          api.file.listdir([]),
      ),
  )
