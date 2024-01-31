# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'exoneration_util',
]



def RunSteps(api):
  failure_rates = api.exoneration_util.query_failure_rate([])
  api.assertions.assertEqual(failure_rates, [])
  def_map = {'build_target': 'bt', 'board': 'board'}
  test_variant = {'testId': 'test_name', 'variant': {'def': def_map}}
  failure_rates = api.exoneration_util.query_failure_rate([test_variant] * 220)


def GenTests(api):
  yield api.test(
      'basic',
      # Check that LUCI Analysis gets called thrice on 220 input size.
      api.post_check(post_process.MustRun,
                     'query LUCI Analysis for failure rates (3).rpc call'),
      api.post_process(post_process.DropExpectation))
