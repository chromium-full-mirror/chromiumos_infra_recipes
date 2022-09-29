# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.workspace_util.examples.test import TestInputProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'cros_source',
    'src_state',
    'test_util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  config = api.cros_source.configure_builder(commit, changes)

  # Note that any use case involving a chroot (SDK) will say:
  #   with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
  with api.workspace_util.setup_workspace(), \
      api.workspace_util.sync_to_commit():
    api.workspace_util.apply_changes(
        ignore_missing_projects=properties.ignore_missing_projects)
    if changes:
      api.workspace_util.checkout_change(changes[0])
    else:
      # Shouldn't do anything.
      api.workspace_util.checkout_change()
    want = changes if config.build.apply_gerrit_changes and changes else []
    api.assertions.assertEqual(len(want), len(api.workspace_util.patch_sets))
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
      ignore_missing_projects (bool): Value to pass to apply_changes.

    Args:
      *args (list):  Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # The combination of *args and **kwargs above makes this the least messy way
    # to have our own parameters, with defaults.
    toolchain_cls_applied = kwargs.pop('toolchain_cls_applied', False)
    ignore_missing_projects = kwargs.pop('ignore_missing_projects', False)

    cq = kwargs.get('cq', False)
    build_target = 'atlas' if cq else 'amd64-generic'
    has_cls = cq or kwargs.get('extra_changes')

    ret = api.test_util.test_child_build(build_target, **kwargs).build

    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = not toolchain_cls_applied
    ret += api.properties(
        TestInputProperties(
            expected_toolchain_cls_applied=toolchain_cls_applied,
            ignore_missing_projects=ignore_missing_projects))

    if has_cls:
      ret += api.step_data(
          'detect toolchain change.path relevancy check.read output file',
          api.file.read_raw(content=resp.SerializeToString()))
    return api.test(name, ret, *args)

  # The default Postsubmit build.
  yield test('has-commit-and-no-changes',)

  # The default CQ build.
  yield test('has-changes-and-no-commit', cq=True)

  yield test('ignore-missing-projects', cq=True, ignore_missing_projects=True)

  yield test('has-no-commit-and-no-changes', revision=None)

  yield test('has-toolchain-changes', cq=True, toolchain_cls_applied=True)

  yield test('release', git_repo=api.src_state.external_manifest.url,
             git_ref='refs/heads/release-R86.13421.B')
