# -*- coding: utf-8 -*-

# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.assertions.assertEqual(
      api.cros_history.get_annealing_from_snapshot('fake-snapshot-id')[0].id,
      123)


def GenTests(api):
  yield api.test(
      'get-annealing-from-snapshot',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()]))
