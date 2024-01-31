# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'iterutils',
]



def RunSteps(api):
  api.assertions.assertEqual(
      api.iterutils.get_one(
          ['abc', 'def'],
          lambda s: s.startswith('ab'),
          "Expected string starting with 'ab'",
      ),
      'abc',
  )

  with api.assertions.assertRaisesRegexp(ValueError,
                                         "Expected string starting with 'ab'"):
    api.iterutils.get_one(
        ['ac', 'def'],
        lambda s: s.startswith('ab'),
        "Expected string starting with 'ab'",
    )


def GenTests(api):
  yield api.test('basic')
