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
  api.assertions.assertEqual(
      api.exoneration_util.get_tastless_name('tast.test_name'), 'test_name')
  api.assertions.assertEqual(
      api.exoneration_util.get_tastless_name('test_name'), 'test_name')


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
