# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import copy
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
gerrit_changes_json_no_labels = copy.deepcopy(gerrit_changes_json)
_ = [chg.pop('labels') for chg in gerrit_changes_json_no_labels]


require_cq_approved = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.COMMIT_QUEUE,
    kind=gerrit_api.LabelConstraintKind.APPROVED)
require_cq_unapproved = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.COMMIT_QUEUE,
    kind=gerrit_api.LabelConstraintKind.UNAPPROVED)
require_cq_nonzero = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.COMMIT_QUEUE,
    kind=gerrit_api.LabelConstraintKind.ANY_NONZERO_VOTE)
require_botcommit_approved = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.BOT_COMMIT,
    kind=gerrit_api.LabelConstraintKind.APPROVED)
bogus_constraint_type = gerrit_api.LabelConstraint(
    label=gerrit_api.Label.COMMIT_QUEUE, kind=-1)
constraint_dict = {
    'require_cq_approved': [require_cq_approved],
    'require_cq_unapproved': [require_cq_unapproved],
    'require_cq_nonzero': [require_cq_nonzero],
    'require_botcommit_approved': [require_botcommit_approved],
    'bogus_constraint_type': [bogus_constraint_type],
}


def RunSteps(api: recipe_api.RecipeApi):
  """Main test logic: run query_changes() and assert about the output.

  The direct gerrit_client step results can be mocked in cases via
  GerritTestApi.set_query_changes_response(), but query_changes() runs
  additional logic to process the step output.
  """
  changes = api.gerrit.query_changes(
      'https://chromium-review.googlesource.com', [('topic', 'pupr')],
      constraint_dict.get(api.properties['label_constraints']))
  actual_change_numbers = [change.change for change in changes]
  actual_change_numbers.sort()
  expected_change_numbers = list(api.properties['expected_change_numbers'])
  expected_change_numbers.sort()
  api.assertions.assertListEqual(actual_change_numbers, expected_change_numbers)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Define test cases."""
  # Define constraints

  yield api.test(
      'basic',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json_no_labels,
          'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827, 91828],
                     label_constraints=None),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'require-cq-approved',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827],
                     label_constraints='require_cq_approved'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'require-cq-unapproved',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91828],
                     label_constraints='require_cq_unapproved'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'require-cq-nonzero',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[91827],
                     label_constraints='require_cq_nonzero'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'labels-not-present',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json_no_labels,
          'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[],
                     label_constraints='require_cq_approved'),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'specific-label-missing',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[],
                     label_constraints='require_botcommit_approved'),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'invalid-constraint-type',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com'),
      api.properties(expected_change_numbers=[],
                     label_constraints='bogus_constraint_type'),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
