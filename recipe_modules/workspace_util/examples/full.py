# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_infra_config',
    'src_state',
    'test_util',
    'workspace_util',
]

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.workspace_util.examples.test import (
    TestInputProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine import post_process

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  # Configure the builder so that we have
  # self.m.cros_infra_config.gitiles_commit. All of our tests will be with
  # builders that have configs.
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  # Note that any use case involving a chroot (SDK) will say:
  #   with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
  with api.workspace_util.setup_workspace(), \
      api.workspace_util.sync_to_commit():
    api.workspace_util.apply_changes(
        fail_not_applicable=properties.fail_not_applicable)
    want = changes if config.build.apply_gerrit_changes and changes else []
    api.assertions.assertEqual(len(want), len(api.workspace_util.patch_sets))
    api.assertions.assertEqual(len(want), len(api.workspace_util.commits))
    api.assertions.assertEqual(api.context.cwd,
                               api.workspace_util.workspace_path)

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
      fail_not_applicable (bool): Value to pass to apply_changes.

    Args:
      *args (list):  Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # The combination of *args and **kwargs above makes this the least messy way
    # to have our own parameters, with defaults.
    toolchain_cls_applied = kwargs.pop('toolchain_cls_applied', False)
    fail_not_applicable = kwargs.pop('fail_not_applicable', False)

    cq = kwargs.get('cq', False)
    build_target = 'atlas' if cq else 'amd64-generic'
    has_cls = cq or kwargs.get('extra_changes')

    ret = api.test_util.test_child_build(build_target, **kwargs).build

    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = not toolchain_cls_applied
    ret += api.properties(
        TestInputProperties(
            expected_toolchain_cls_applied=toolchain_cls_applied,
            fail_not_applicable=fail_not_applicable))

    if has_cls:
      ret += api.step_data(
          'detect toolchain change.path relevancy check.read output file',
          api.file.read_raw(content=resp.SerializeToString()))
    return api.test(name, ret, *args)

  # The default Postsubmit build.
  yield test('has_commit_and_no_changes')

  # The default CQ build.
  yield test('has_changes_and_no_commit', cq=True)

  yield test('fail_not_applicable', cq=True, fail_not_applicable=True)

  yield test('has_no_commit_and_no_changes', revision=None)

  yield test('has_toolchain_changes', cq=True, toolchain_cls_applied=True)
