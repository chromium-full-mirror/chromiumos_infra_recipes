# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy

from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from RECIPE_MODULES.chromeos.gerrit.api import Label, LabelConstraint, LabelConstraintType

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'expected_change_numbers':
        Property(help='The change IDs which the query should return.'),
    'label_constraints':
        Property(
            help='List of constraints that should be applied to returned changes.',
            default=None)
}

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
            },
            'Commit-Queue': {},
        },
    },
]
gerrit_changes_json_no_labels = copy.deepcopy(gerrit_changes_json)
_ = [chg.pop('labels') for chg in gerrit_changes_json_no_labels]

values_dict = {
    91827:
        dict(
            status='NEW', created='2021-01-25 13:11:20.000000000',
            change_id='Ideadbeef', project='chromium/src',
            has_review_started=False, branch='main', subject='Overridden title',
            revisions={
                '184ebe53805e102605d11f6b143486d15c23a09c': {
                    '_number': '23981',
                    'commit': {
                        'message': 'Overridden change commit message',
                    }
                }
            }),
    91828:
        dict(
            status='MERGED',
            created='2021-02-25 13:11:20.000000000',
            submitted='2021-02-26 13:11:20.000000000',
            change_id='Ideadbeef02',
            project='chromium/src',
            has_review_started=True,
            branch='main',
            subject='Overridden title',
        )
}


def RunSteps(api, expected_change_numbers, label_constraints):
  changes = api.gerrit.query_changes('https://chromium-review.googlesource.com',
                                     [('topic', 'pupr')], label_constraints)
  actual_change_numbers = [change.change for change in changes]
  actual_change_numbers.sort()
  expected_change_numbers.sort()
  api.assertions.assertListEqual(actual_change_numbers, expected_change_numbers)


def GenTests(api):
  # Define constraints
  require_cq_approved = LabelConstraint(label=Label.COMMIT_QUEUE,
                                        type=LabelConstraintType.APPROVED)
  require_cq_unapproved = LabelConstraint(label=Label.COMMIT_QUEUE,
                                          type=LabelConstraintType.UNAPPROVED)
  require_botcommit_approved = LabelConstraint(
      label=Label.BOT_COMMIT, type=LabelConstraintType.APPROVED)
  bogus_constraint_type = LabelConstraint(label=Label.COMMIT_QUEUE, type=-1)

  yield api.test(
      'basic',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json_no_labels,
          'https://chromium-review.googlesource.com', values_dict),
      api.properties(expected_change_numbers=[91827, 91828]),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'require-cq-approved',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com',
          values_dict),
      api.properties(expected_change_numbers=[91827],
                     label_constraints=[require_cq_approved]),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'require-cq-unapproved',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com',
          values_dict),
      api.properties(expected_change_numbers=[91828],
                     label_constraints=[require_cq_unapproved]),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'labels-not-present',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json_no_labels,
          'https://chromium-review.googlesource.com', values_dict),
      api.properties(expected_change_numbers=[],
                     label_constraints=[require_cq_approved]),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'specific-label-missing',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com',
          values_dict),
      api.properties(expected_change_numbers=[],
                     label_constraints=[require_botcommit_approved]),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'invalid-constraint-type',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com',
          values_dict),
      api.properties(expected_change_numbers=[],
                     label_constraints=[bogus_constraint_type]),
      api.post_check(post_process.StepFailure,
                     'query https://chromium-review.googlesource.com'),
      api.post_process(post_process.DropExpectation))
