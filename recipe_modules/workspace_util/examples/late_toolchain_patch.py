# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for workspace_util when toolchain changes are applied late.

Intended for flows like incremental builders. See b/329271972.
"""

from typing import Generator

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.workspace_util.examples.test import TestInputProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_source',
    'test_util',
    'workspace_util',
]

PROPERTIES = TestInputProperties


def RunSteps(api: RecipeApi, properties: TestInputProperties) -> None:
  commit = api.buildbucket.gitiles_commit
  changes = [
      GerritChange(host='chromium-review.googlesource.com', change=1234,
                   patchset=2),
  ]
  api.cros_source.configure_builder(commit, changes)

  with api.workspace_util.setup_workspace(), \
      api.workspace_util.sync_to_commit():
    # This should always return False, since changes haven't yet been applied.
    api.assertions.assertFalse(api.workspace_util.detect_toolchain_cls(None))
    api.assertions.assertFalse(api.workspace_util.toolchain_cls_applied)

    api.workspace_util.apply_changes()
    expected_toolchain_cls = properties.expected_toolchain_cls_applied
    api.workspace_util.detect_toolchain_cls(None,
                                            test_value=expected_toolchain_cls)
    api.assertions.assertEqual(expected_toolchain_cls,
                               api.workspace_util.toolchain_cls_applied)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def test(name: str, toolchain_cls_applied: bool = False) -> TestData:
    ret = api.test_util.test_child_build('atlas').build
    ret += api.properties(
        TestInputProperties(
            expected_toolchain_cls_applied=toolchain_cls_applied))
    return api.test(name, ret, api.post_process(post_process.DropExpectation))

  yield test('has-toolchain-changes', toolchain_cls_applied=True)
  yield test('no-toolchain-changes', toolchain_cls_applied=False)
