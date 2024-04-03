# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for chrome_module_child_props()."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'orch_menu',
]


def RunSteps(api):
  api.assertions.assertDictEqual(api.orch_menu.chrome_module_child_props,
                                 dict(api.properties.get('expected_value')))


def GenTests(api):

  yield api.orch_menu.test(
      'no-chromium-src-ref',
      api.properties(expected_value={}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.orch_menu.test(
      'with-chromium-src-ref',
      api.buildbucket.try_build(
          tags=api.cros_tags.tags(cq_cl_tag='chromium_src_ref:foo1234ref')),
      api.properties(expected_value={'version': 'foo1234ref'}),
      api.post_process(post_process.DropExpectation),
  )
