# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab_results',
]



def RunSteps(api):
  responses = api.skylab_results.get_previous_results([], [])
  api.assertions.assertEqual(len(responses), 0)


def GenTests(api):
  yield api.test('basic')
