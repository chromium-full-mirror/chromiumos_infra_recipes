# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that handle_open_changes() runs the expected process."""
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import GerritChange
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange as LuciGerritChange
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import NO_RETRY
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import RETRY_LATEST_OR_LATEST_PINNED
from PB.recipes.chromeos.generator import RETRY_LATEST_PINNED
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
    'gerrit',
    'git',
    'pupr_gerrit_interface',
    'pupr_local_uprev',
    'src_state',
    'test_util',
]

PROPERTIES = {
    'existing_cls_policy': Property(),
    'no_existing_cls_policy': Property(),
    'retry_cl_policy': Property(),
    'outdated_cls_policy': Property(),
    'expected': Property(default=True),
    'retry_only': Property(default=False),
    'rebase_before_retry': Property(default=False),
    'changes': Property(default=1),
}

BUILD_TARGETS = [BuildTarget(name='build-target')]
PACKAGE_CHROME = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')
PACKAGES = [PACKAGE_CHROME]


def RunSteps(api: recipe_api.RecipeApi, existing_cls_policy: any,
             no_existing_cls_policy: any, retry_cl_policy: any,
             outdated_cls_policy: any, expected: bool, retry_only: bool,
             rebase_before_retry: bool, changes: int):
  api.pupr_gerrit_interface.set_generator_attributes(rebase_before_retry)

  # Arrange
  api.pupr_local_uprev.set_generator_attributes(
      packages=PACKAGES,
      build_targets=BUILD_TARGETS,
  )

  api.assertions.assertEqual(
      expected,
      api.pupr_gerrit_interface.handle_open_changes(
          [
              GerritChange(host='chromium-review.googlesource.com',
                           change=1234 + i) for i in range(0, changes)
          ], {
              'cros': [
                  ProjectInfo(name='galaxy', path='project', remote='cros',
                              branch=f'{api.src_state.workspace_path}',
                              rrev=api.src_state.workspace_path)
              ]
          },
          BranchPolicy(pattern='.*', repl='',
                       reviewers=[Reviewer(email='a@example.com')],
                       no_existing_cls_policy=no_existing_cls_policy,
                       existing_cls_policy=existing_cls_policy,
                       retry_cl_policy=retry_cl_policy,
                       outdated_cls_policy=outdated_cls_policy), 'topic',
          retry_only))


def GenTests(api: recipe_test_api.RecipeTestApi):

  gerrit_changes = [
      GerritChange(
          host="chromium-review.googlesource.com",
          change=1234,
      ),
  ]

  yield api.test(
      'basic',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rebase-before-retry',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT,
                     rebase_before_retry=True),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_PINNED',
          'chromium-review.googlesource.com', 1234, 'current', False),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'hashtags': ['pupr-retry-pinned'],
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date':
                          1234,
                      'tag':
                          'autogenerated:cq:full-run:1234',
                      'message':
                          'Patch Set 1234:  This CL has failed the run. Reason:'
                  }],
              },
          },
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED.rebase CL 1234.get CL 1234 description',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'hashtags': ['pupr-retry-pinned'],
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date':
                          1234,
                      'tag':
                          'autogenerated:cq:full-run:1234',
                      'message':
                          'Patch Set 1234:  This CL has failed the run. Reason:'
                  }],
                  'message':
                      'a quick description\n\nChange-Id: deadbeef\n\nPupr-Upstream-Versions: []\n'
              },
          },
      ),
      api.cros_build_api.set_api_return(
          'apply retry policy RETRY_LATEST_PINNED.rebase CL 1234.try uprev chromeos-base/chromeos-chrome',
          'PackageService/UprevVersionedPackage',
          step_name='uprev versioned package',
          data='{"responses":[{"additional_commit_info": "additional info to be rendered on uprev cl.", "modified_ebuilds": [{"path": "[CLEANUP]/chromiumos_workspace/src/overlay/foo.ebuild"}], "version": "1.2.3"}]}'
      ), api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              LuciGerritChange(host='chromium-review.googlesource.com',
                               change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_PINNED.upload patch set for Change-Id 1234'
      ),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_PINNED.retry CL 1234'),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rebase-before-retry-already-mergeable',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT,
                     rebase_before_retry=True),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_PINNED',
          'chromium-review.googlesource.com', 1234, 'current', True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'hashtags': ['pupr-retry-pinned'],
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date':
                          1234,
                      'tag':
                          'autogenerated:cq:full-run:1234',
                      'message':
                          'Patch Set 1234:  This CL has failed the run. Reason:'
                  }],
              },
          },
      ), api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              LuciGerritChange(host='chromium-review.googlesource.com',
                               change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(post_process.DoesNotRunRE, r'.*\.rebase CL 1234.*'),
      api.post_check(post_process.DoesNotRunRE,
                     r'.*\.upload patch set for Change-Id 1234'),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_PINNED.retry CL 1234'),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rebase-before-retry-already-running-and-mergeable',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT,
                     rebase_before_retry=True),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          'chromium-review.googlesource.com', 1234, 'current', True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date': 1234,
                      'tag': 'autogenerated:cq:dry-run:1234',
                      'message': 'Patch Set 5:  Dry run: CV is trying the patch'
                  }],
              },
          },
      ), api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              LuciGerritChange(host='chromium-review.googlesource.com',
                               change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(post_process.DoesNotRunRE, r'.*\.rebase CL 1234.*'),
      api.post_check(post_process.DoesNotRunRE,
                     r'.*\.upload patch set for Change-Id 1234'),
      api.post_check(post_process.DoesNotRunRE, '.*retry CL 1234'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rebase-before-retry-already-running-and-rebase',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT,
                     rebase_before_retry=True),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          'chromium-review.googlesource.com', 1234, 'current', False),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date': 1234,
                      'tag': 'autogenerated:cq:dry-run:1234',
                      'message': 'Patch Set 5:  Dry run: CV is trying the patch'
                  }],
              },
          },
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1234.get CL 1234 description',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date':
                          1234,
                      'tag':
                          'autogenerated:cq:full-run:1234',
                      'message':
                          'Patch Set 1234:  This CL has failed the run. Reason:'
                  }],
                  'message':
                      'a quick description\n\nChange-Id: deadbeef\n\nPupr-Upstream-Versions: []\n'
              },
          },
      ),
      api.cros_build_api.set_api_return(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.rebase CL 1234.try uprev chromeos-base/chromeos-chrome',
          'PackageService/UprevVersionedPackage',
          step_name='uprev versioned package',
          data='{"responses":[{"additional_commit_info": "additional info to be rendered on uprev cl.", "modified_ebuilds": [{"path": "[CLEANUP]/chromiumos_workspace/src/overlay/foo.ebuild"}], "version": "1.2.3"}]}'
      ), api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              LuciGerritChange(host='chromium-review.googlesource.com',
                               change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(post_process.MustRunRE, r'.*\.rebase CL 1234.*'),
      api.post_check(
          post_process.MustRunRE,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.upload patch set for Change-Id 1234'
      ),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED.retry CL 1234'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rebase-before-retry-dry-run-passed',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT,
                     rebase_before_retry=True, changes=2),
      api.gerrit.set_get_change_mergeable(
          'apply retry policy RETRY_LATEST_PINNED',
          'chromium-review.googlesource.com', 1234, 'current', False),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED',
          [
              GerritChange(
                  host="chromium-review.googlesource.com",
                  change=1234,
              ),
              GerritChange(
                  host="chromium-review.googlesource.com",
                  change=1235,
              ),
          ],
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date': 1234,
                      'tag': 'autogenerated:cq:dry-run:1234',
                      'message': 'Patch Set 1234:  This CL has passed the run'
                  }],
              },
              1235: {
                  'created': "2023-01-09 13:10:20.000000000",
              },
          },
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED.rebase CL 1234.get CL 1234 description',
          gerrit_changes,
          {
              1234: {
                  'patch_set':
                      5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch':
                      'main',
                  'created':
                      "2023-01-09 13:11:20.000000000",
                  'messages': [{
                      'date':
                          1234,
                      'tag':
                          'autogenerated:cq:full-run:1234',
                      'message':
                          'Patch Set 1234:  This CL has failed the run. Reason:'
                  }],
                  'message':
                      'a quick description\n\nChange-Id: deadbeef\n\nPupr-Upstream-Versions: []\n'
              },
          },
      ),
      api.cros_build_api.set_api_return(
          'apply retry policy RETRY_LATEST_PINNED.rebase CL 1234.try uprev chromeos-base/chromeos-chrome',
          'PackageService/UprevVersionedPackage',
          step_name='uprev versioned package',
          data='{"responses":[{"additional_commit_info": "additional info to be rendered on uprev cl.", "modified_ebuilds": [{"path": "[CLEANUP]/chromiumos_workspace/src/overlay/foo.ebuild"}], "version": "1.2.3"}]}'
      ), api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              LuciGerritChange(host='chromium-review.googlesource.com',
                               change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_PINNED.upload patch set for Change-Id 1234'
      ),
      api.post_check(post_process.MustRun,
                     'apply retry policy RETRY_LATEST_PINNED.retry CL 1234'),
      api.post_check(
          post_process.MustRun,
          'apply retry policy RETRY_LATEST_PINNED.abandon CLs before passed CQ+1 CL'
      ),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'frozen-skip-retry',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED',
          gerrit_changes,
          {
              1234: {
                  'patch_set': 5,
                  'files': {
                      'a/b/d/test.txt': {},
                  },
                  'branch': 'main',
                  'hashtags': ['pupr-freeze-retries'],
                  'created': "2023-01-09 13:11:20.000000000",
              },
          },
      ), api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-retry',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN, retry_cl_policy=NO_RETRY,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_check(post_process.DoesNotRun, 'apply retry policy NO_RETRY'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-rebase',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN, retry_cl_policy=NO_RETRY,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_check(post_process.DoesNotRun, 'apply retry policy NO_RETRY'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'outdated-abandon',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_ABANDON, expected=False),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.comment on CL 1234'
      ),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.abandon CL 1234'),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-uprev',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN,
                     retry_cl_policy=RETRY_LATEST_PINNED,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=False,
                     changes=0, rebase_before_retry=True),
      api.post_check(post_process.DoesNotRun, 'outdated CLs'),
      api.post_check(post_process.StepSuccess,
                     'apply retry policy RETRY_LATEST_PINNED'),
      api.post_process(post_process.DropExpectation))
