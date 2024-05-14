# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test recipe for gerrit.query_change_infos call"""
from typing import Generator

from RECIPE_MODULES.chromeos.gerrit import api as gerrit_api
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

gerrit_changes_json = [
    {
        '_number': 91827,
        'project': 'chromium/src',
        'labels': {
            'Code-Review': {},
            'Commit-Queue': {
                'approved': {
                    '_account_id': 123456,
                },
                'all': [{
                    '_account_id': 654321,
                    'value': 1,
                },],
            },
        },
        'current_revision_numbe': 5,
        'current_revision': 'ecd0109080cc5c13bfae6d1cc9a918a51219c22d',
        'revisions': {
            'ecd0109080cc5c13bfae6d1cc9a918a51219c22d': {
                'kind':
                    'TRIVIAL_REBASE',
                '_number':
                    5,
                'created':
                    '2019-05-13 15:00:09.000000000',
                'uploader': {
                    '_account_id': 1234
                },
                'ref':
                    'refs/changes/14/91827/5',
                'fetch': {
                    'repo': {
                        'url': 'chromiumos/platform/ec',
                        'ref': 'refs/changes/14/91827/5'
                    },
                    'http': {
                        'url':
                            'https://chromium.googlesource.com/chromiumos/platform/ec',
                        'ref':
                            'refs/changes/14/91827/5'
                    }
                },
                'branch':
                    'refs/heads/main',
                'commit_with_footers':
                    'chromium/src/sample: My Sample Change\n\nDefining sample change\n\nBUG=b:3434\nTEST=CQ\n\nChange-Id: Ic1b05af924d907fb1c694e6a520fd57da820a48c\nReviewed-on: https://chromium-review.googlesource.com/c/chromium/src//+/91827\nReviewed-by: Jon Doe <jondoe@chromium.org>\n'
            }
        },
    },
    {
        '_number': 91828,
        'project': 'chromium/src',
        'labels': {
            'Code-Review': {
                'approved': {
                    '_account_id': 123457,
                },
                'all': [],
            },
            'Commit-Queue': {},
        },
    },
]
require_cq_approved = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.COMMIT_QUEUE,
    kind=gerrit_api.LabelConstraintKind.APPROVED)
constraint_dict = {
    'require_cq_approved': [require_cq_approved],
}


def RunSteps(api: recipe_api.RecipeApi):
  """Main test logic: run query_change_infos() and assert about the output.

  The direct gerrit_client step results can be mocked in cases via
  GerritTestApi.set_query_changes_response().
  """
  oparams = api.properties['o_params']
  oparams = list(oparams) if oparams is not None else []
  label_constraints = constraint_dict.get(api.properties['label_constraints'])
  changes = api.gerrit.query_change_infos(
      'https://chromium-review.googlesource.com', [('topic', 'pupr')],
      label_constraints, oparams)
  actual_change_numbers = [change.get('_number') for change in changes]
  expected_change_numbers = list(api.properties['expected_change_numbers'])
  api.assertions.assertCountEqual(
      expected_change_numbers, actual_change_numbers,
      'actual_change_numbers len is %d and expected is %d' %
      (len(actual_change_numbers), len(expected_change_numbers)))


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Define test cases."""

  yield api.test(
      'basic',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827, 91828],
                     label_constraints=None, o_params=None),
      api.post_process(
          post_process.StepCommandContains,
          'query https://chromium-review.googlesource.com.gerrit changes',
          ['-p', 'topic=pupr']),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'no-labels-with-o_params',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827, 91828],
                     label_constraints=None, o_params=['COMMIT_FOOTERS']),
      api.post_process(
          post_process.StepCommandContains,
          'query https://chromium-review.googlesource.com.gerrit changes',
          ['-p', 'topic=pupr', '-o', 'COMMIT_FOOTERS']),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'with_label-require-cq-approved-no-o_params',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827],
                     label_constraints='require_cq_approved', o_params=None),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'require-cq-approved-with-o_params',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827],
                     label_constraints='require_cq_approved',
                     o_params=['COMMIT_FOOTERS']),
      api.post_process(
          post_process.StepCommandContains,
          'query https://chromium-review.googlesource.com.gerrit changes',
          ['-p', 'topic=pupr', '-o', 'COMMIT_FOOTERS']),
      api.post_process(post_process.DropExpectation),
  )
