# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that handle_open_changes() runs the expected process."""
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import GerritChange
from PB.chromiumos.common import PackageInfo
from PB.recipe_modules.chromeos.pupr_gerrit_interface.tests.tests import \
  HandleOutdatedChangesProperties
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import RETRY_LATEST_PINNED
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api


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

PROPERTIES = HandleOutdatedChangesProperties

BUILD_TARGETS = [BuildTarget(name='build-target')]
PACKAGE_CHROME = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')
PACKAGES = [PACKAGE_CHROME]

change_infos = [{
    'id': 'fully~qualified~changeid',
    'status': 'MERGED',
    'created': '2017-01-30 13:11:20.000000000',
    '_number': 91827,
    'change_id': 'Ideadbeef',
    'project': 'chromium/src',
    'has_review_started': False,
    'branch': 'main',
    'subject': 'Change title',
    'revisions': {
        '184ebe53805e102605d11f6b143486d15c23a09c': {
            '_number': 1,
            'commit': {
                'message': 'Change commit message',
            },
        },
    },
}]

gerrit_changes = [
    GerritChange(change=91827, host='chromium-review.googlesource.com')
]

merged_value_dict = {
    91827: {
        'change_number': 91827,
        'project': 'chromium/src',
        'status': 'MERGED'
    }
}


def RunSteps(api: recipe_api.RecipeApi,
             properties: HandleOutdatedChangesProperties):
  # Arrange
  api.pupr_local_uprev.set_generator_attributes(
      packages=PACKAGES,
      build_targets=BUILD_TARGETS,
  )

  mrm = api.pupr_gerrit_interface.find_most_recently_merged_uprev(
      {
          'cros': [
              ProjectInfo(name='galaxy', path='project', remote='cros',
                          branch=f'{api.src_state.workspace_path}',
                          rrev=api.src_state.workspace_path)
          ]
      }, 'topic') if properties.changes > 0 else None
  remaining_changes = api.pupr_gerrit_interface.handle_outdated_changes(
      [
          GerritChange(host='chromium-review.googlesource.com', change=1234 + i)
          for i in range(0, properties.changes)
      ], mrm,
      BranchPolicy(pattern='.*', repl='',
                   reviewers=[Reviewer(email='a@example.com')],
                   no_existing_cls_policy=FULL_RUN, existing_cls_policy=SUBMIT,
                   retry_cl_policy=RETRY_LATEST_PINNED,
                   outdated_cls_policy=properties.outdated_cls_policy),
      properties.retry_only)
  expected_remaining = ([
      GerritChange(host='chromium-review.googlesource.com', change=1234 + i)
      for i in range(0, properties.changes)
  ] if properties.expected else [])
  api.assertions.assertEqual(expected_remaining, remaining_changes)


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=True,
                     changes=1),
      api.pupr_gerrit_interface.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes, merged_value_dict),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.add comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'outdated-abandon',
      api.properties(outdated_cls_policy=OUTDATED_ABANDON, changes=1,
                     expected=False),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          change_infos, 'https://chromium-review.googlesource.com'),
      api.pupr_gerrit_interface.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes, merged_value_dict),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.add comment on CL 1234'
      ),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.abandon CL 1234'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-rebase',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=True,
                     changes=1),
      api.pupr_gerrit_interface.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes, merged_value_dict),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.add comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-recent-merged-cl',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=False,
                     changes=0), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-recent-merged-cl-with-changes',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=True,
                     changes=1),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          [], 'https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation))

  ignored_value_dict = {
      1234: {
          'change_number': 1234,
          'project': 'chromium/src',
          'status': 'NEW',
          'hashtags': ['pupr-ignored'],
          'created': '2016-01-01 00:00:00.000000000',
      }
  }
  yield api.test(
      'outdated-pupr-ignored-abandon',
      api.properties(outdated_cls_policy=OUTDATED_ABANDON, expected=False,
                     changes=1),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          change_infos, 'https://chromium-review.googlesource.com'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes, merged_value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          '',
          [GerritChange(change=1234, host='chromium-review.googlesource.com')],
          ignored_value_dict),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.abandon CL 1234'),
      api.post_process(post_process.DropExpectation))

  v1_value_dict = {
      1234: {
          'change_number': 1234,
          'project': 'chromium/src',
          'status': 'NEW',
          'labels': {
              'Verified': {
                  'value': -1
              }
          },
          'created': '2016-01-01 00:00:00.000000000',
      }
  }
  yield api.test(
      'outdated-verified-minus-one-abandon',
      api.properties(outdated_cls_policy=OUTDATED_ABANDON, expected=False,
                     changes=1),
      api.gerrit.set_query_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          change_infos, 'https://chromium-review.googlesource.com'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'examine outdated CLs.merged CLs from chromium host (within 30 days)',
          gerrit_changes, merged_value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          '',
          [GerritChange(change=1234, host='chromium-review.googlesource.com')],
          v1_value_dict), api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.abandon CL 1234'),
      api.post_process(post_process.DropExpectation))
