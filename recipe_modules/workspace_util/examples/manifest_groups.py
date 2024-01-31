# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Any
from typing import Generator

from PB.recipe_modules.chromeos.workspace_util.examples.test import TestInputProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_cache',
    'cros_source',
    'repo',
    'test_util',
    'workspace_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api: RecipeApi, properties: TestInputProperties) -> None:
  # Configure the builder so that we have
  # self.m.cros_source.gitiles_commit. All of our tests will be with
  # builders that have configs.
  _ = api.cros_source.configure_builder()
  cache_dir = api.cros_cache.create_cache_dir('temp_cache')
  with api.workspace_util.sync_to_manifest_groups(['group1', 'group2'], [
      api.repo.LocalManifest(repo='http://repo.url', path='manifest_path',
                             branch=None)
  ], cache_dir):
    api.workspace_util.apply_changes()

  api.workspace_util.detect_toolchain_cls(None)
  api.assertions.assertEqual(properties.expected_toolchain_cls_applied,
                             api.workspace_util.toolchain_cls_applied)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def test(name: str, *test_case_args: Any, toolchain_cls_applied: bool = False,
           **test_build_kwargs: Any) -> TestData:
    """A test, with properties

    This function creates a test child_build from kwargs, and then calls
    api.test() to create the TestData for a test.

    Args:
      name: Name of the test case.
      *test_case_args: Arguments to pass to api.test.
      toolchain_cls_applied: Whether there are toolchain_cls.
      **test_build_kwargs: Keyword arguments to pass to test_util.test_build.

    Returns:
      TestData for the test.
    """
    cq = test_build_kwargs.get('cq', False)
    build_target = 'atlas' if cq else 'amd64-generic'
    has_cls = cq or test_build_kwargs.get('extra_changes')

    ret = api.test_util.test_child_build(build_target,
                                         **test_build_kwargs).build

    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = not toolchain_cls_applied
    ret += api.properties(
        TestInputProperties(
            expected_toolchain_cls_applied=toolchain_cls_applied))

    if has_cls:
      ret += api.step_data('detect toolchain change.read output file',
                           api.file.read_raw(content=resp.SerializeToString()))
    return api.test(name, ret, *test_case_args)

  # The default Postsubmit build.
  yield test('has-commit-and-no-changes',)

  # The default CQ build.
  yield test('has-changes-and-no-commit', cq=True)

  yield test('has-no-commit-and-no-changes', revision=None)

  yield test('has-toolchain-changes', cq=True, toolchain_cls_applied=True)
