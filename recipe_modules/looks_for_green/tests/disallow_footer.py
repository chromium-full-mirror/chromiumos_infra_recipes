# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import post_process

from PB.chromiumos.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git_footers',
    'looks_for_green',
]

PROPERTIES = {'expected_disallow': Property(default=False)}

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api, expected_disallow):
  gerrit_changes = [
      GerritChange(
          host="chromium-review.googlesource.com",
          change=1234,
      )
  ]

  disallow = api.looks_for_green.found_disallow_lfg_footer(gerrit_changes)
  api.assertions.assertEqual(expected_disallow, disallow)


def GenTests(api):
  yield api.test(
      'disallow-footer',
      api.properties(expected_disallow=True),
      api.git_footers.simulated_get_footers(['True'],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-disallow-footer',
      api.git_footers.simulated_get_footers([],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'false-disallow-footer',
      api.git_footers.simulated_get_footers(['False'],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'invalid-disallow-footer',
      api.properties(expected_disallow=True),
      api.git_footers.simulated_get_footers(['something'],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'some-disallow-footer',
      api.properties(expected_disallow=True),
      api.git_footers.simulated_get_footers(['False', 'True', 'False'],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )
