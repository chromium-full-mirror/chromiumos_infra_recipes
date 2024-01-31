# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import GerritChange
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git_footers',
    'looks_for_green',
]



def RunSteps(api):
  gerrit_changes = [
      GerritChange(
          host='chromium-review.googlesource.com',
          change=1234,
      )
  ]

  disallow = api.looks_for_green.found_disallow_lfg_footer(gerrit_changes)
  api.assertions.assertEqual(api.properties['expected_disallow'], disallow)


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
      api.properties(expected_disallow=False),
      api.git_footers.simulated_get_footers([],
                                            'check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'false-disallow-footer',
      api.properties(expected_disallow=False),
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
