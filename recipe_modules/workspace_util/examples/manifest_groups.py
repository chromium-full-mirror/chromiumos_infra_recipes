# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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

from PB.recipe_modules.chromeos.workspace_util.examples.test import (
    TestInputProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
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


def GenTests(api):

  def test(name, *args, **kwargs):
    """A test, with properties

    This function creates a test child_build from kwargs, and then calls
    api.test() to create the TestData for a test.

    The following arguments are consumed by this method:
      toolchain_cls_applied (bool): Whether there are toolchain_cls.

    Args:
      *args (list):  Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # The combination of *args and **kwargs above makes this the least messy way
    # to have our own parameters, with defaults.
    toolchain_cls_applied = kwargs.pop('toolchain_cls_applied', False)

    cq = kwargs.get('cq', False)
    build_target = 'atlas' if cq else 'amd64-generic'
    has_cls = cq or kwargs.get('extra_changes')

    ret = api.test_util.test_child_build(build_target, **kwargs).build

    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = not toolchain_cls_applied
    ret += api.properties(
        TestInputProperties(
            expected_toolchain_cls_applied=toolchain_cls_applied))

    if has_cls:
      ret += api.step_data(
          'detect toolchain change.path relevancy check.read output file',
          api.file.read_raw(content=resp.SerializeToString()))
    return api.test(name, ret, *args)

  # The default Postsubmit build.
  yield test('has-commit-and-no-changes')

  # The default CQ build.
  yield test('has-changes-and-no-commit', cq=True)

  yield test('has-no-commit-and-no-changes', revision=None)

  yield test('has-toolchain-changes', cq=True, toolchain_cls_applied=True)
