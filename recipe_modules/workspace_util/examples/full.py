# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Any
from typing import Generator

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.workspace_util.examples.test import TestInputProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'cros_source',
    'gerrit',
    'repo',
    'src_state',
    'test_util',
    'workspace_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api: RecipeApi, properties: TestInputProperties) -> None:
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
  # Second run, to check if it returns the same result.
  api.workspace_util.detect_toolchain_cls(None)
  api.assertions.assertEqual(properties.expected_toolchain_cls_applied,
                             api.workspace_util.toolchain_cls_applied)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def test(name: str, *test_case_args: Any, toolchain_cls_applied: bool = False,
           ignore_missing_projects: bool = False,
           **test_build_kwargs: Any) -> TestData:
    """A test, with properties

    This function creates a test child_build from kwargs, and then calls
    api.test() to create the TestData for a test.

    Args:
      name: Name of the test case.
      *test_case_args: Arguments to pass to api.test.
      toolchain_cls_applied: Whether there are toolchain_cls.
      ignore_missing_projects: Value to pass to apply_changes.
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
            expected_toolchain_cls_applied=toolchain_cls_applied,
            ignore_missing_projects=ignore_missing_projects))

    if has_cls:
      ret += api.step_data('detect toolchain change.read output file',
                           api.file.read_raw(content=resp.SerializeToString()))
    return api.test(name, ret, *test_case_args)

  # The default Postsubmit build.
  yield test('has-commit-and-no-changes',)

  # The default CQ build.
  yield test('has-changes-and-no-commit', cq=True)

  yield test('ignore-missing-projects', cq=True, ignore_missing_projects=True)

  yield test('has-no-commit-and-no-changes', revision=None)

  yield test('has-toolchain-changes', cq=True, toolchain_cls_applied=True)

  yield test('release', git_repo=api.src_state.external_manifest.url,
             git_ref='refs/heads/release-R86.13421.B')

  gerrit_change = [
      GerritChange(
          host='chromium-review.googlesource.com',
          project='chromeos/manifest-internal',
          change=123456,
          patchset=7,
      ),
  ]
  gerrit_patch_info = {
      123456: {
          'patch_set': 7,
          'files': {
              '_toolchain.xml': {},
          },
      },
  }

  yield test(
      'has-toolchain-changes-in-manifest',
      api.gerrit.set_gerrit_fetch_changes_response('configure builder',
                                                   gerrit_change,
                                                   gerrit_patch_info),
      api.gerrit.set_gerrit_fetch_changes_response('checkout gerrit change',
                                                   gerrit_change,
                                                   gerrit_patch_info),
      api.gerrit.set_gerrit_fetch_changes_response('cherry-pick gerrit changes',
                                                   gerrit_change,
                                                   gerrit_patch_info),
      api.repo.project_infos_step_data(
          'detect toolchain change.get affected paths',
          data=[
              {
                  'project': 'chromeos/manifest-internal',
                  'path': 'manifest-internal',
              },
          ],
      ),
      # The Gerrit change only contains a change to
      # manifest-internal/_toolchain.xml, but the relevance input should
      # contain that path for both the internal and external manifests
      # (as the diff there will be mirrored by a builder using the
      # external manifest).
      api.post_process(post_process.LogContains, 'detect toolchain change',
                       'relevance_input', (
                           '"manifest/_toolchain.xml"',
                           '"manifest-internal/_toolchain.xml"',
                       )),
      cq=True,
      toolchain_cls_applied=True,
  )
