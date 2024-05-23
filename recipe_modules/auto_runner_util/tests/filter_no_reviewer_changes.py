# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the cls with reviewers functionality."""

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'auto_runner_util',
]


def is_equal(actual_change_infos, expected_cl_numbers):
  actual_set = set((ac['_number']) for ac in actual_change_infos)
  expected_set = set(expected_cl_numbers)
  return actual_set == expected_set


def RunSteps(api):
  change_infos = api.properties['change_infos']
  # pylint: disable=protected-access
  actual = api.auto_runner_util.filter_cls(change_infos, 'Cq-Depend',
                                           api.auto_runner_util._has_reviewers)
  # pylint: enable=protected-access
  expected = api.properties['filtered_hosts']
  for host in expected:
    api.assertions.assertTrue(is_equal(actual[host], expected[host]))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          change_infos={
              'chromium-review.googlesource.com': [
                  {
                      '_number':
                          1234,
                      'current_revision_number':
                          1,
                      'project':
                          'myproject',
                      'revisions': {
                          '1': {
                              '_number':
                                  1,
                              'commit_with_footers':
                                  '''expectations/deqp: Reenable some tests
                              \n\nBUG=b:331633946, b:334001853\nTEST=Run
                              \n\nCq-Depend: chromium:5544628, chromium:5551105\n
                              Change-Id: I8f4da1e457a6f49010c6b0d8777c8e4171581134\n'''
                          }
                      },
                      'reviewer_updates': [{
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1123814
                          },
                          'state': 'CC'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1149894
                          },
                          'state': 'CC'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1308749
                          },
                          'state': 'REVIEWER'
                      }]
                  },
                  {
                      '_number':
                          456,
                      'project':
                          'myproject',
                      'current_revision_number':
                          1,
                      'revisions': {
                          '1': {
                              '_number':
                                  1,
                              'commit_with_footers':
                                  'some footer but no cq depend'
                          }
                      },
                      'reviewer_updates': [{
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1123814
                          },
                          'state': 'CC'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1149894
                          },
                          'state': 'CC'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1308749
                          },
                          'state': 'CC'
                      }]
                  },
                  {
                      '_number': 789,
                      'project': 'myproject',
                      'current_revision_number': 1,
                      'revisions': {
                          '1': {
                              '_number': 1,
                          }
                      }
                  },
              ],
              'chromium-internal-review.googlesource.com': [
                  {
                      '_number': 12340,
                      'current_revision_number': 1,
                      'project': 'myproject',
                      'revisions': {
                          '1': {
                              '_number':
                                  1,
                              'commit_with_footers':
                                  'some footer but no cq depend'
                          }
                      }
                  },
                  {
                      '_number':
                          4560,
                      'project':
                          'myproject',
                      'current_revision_number':
                          1,
                      'revisions': {
                          '1': {
                              '_number':
                                  1,
                              'commit_with_footers':
                                  '''expectations/deqp: Reenable some tests
                              \n\nBUG=b:331633946, b:334001853\nTEST=Run
                              \n\nCq-Depend: chromium:5544628, chromium:5551105\n'''
                          }
                      },
                      'reviewer_updates': [{
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1123814
                          },
                          'state': 'REVIEWER'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1149894
                          },
                          'state': 'REVIEWER'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1308749
                          },
                          'state': 'REVIEWER'
                      }]
                  },
                  {
                      '_number':
                          7890,
                      'project':
                          'myproject',
                      'current_revision_number':
                          1,
                      'revisions': {
                          '1': {
                              '_number': 1,
                          }
                      },
                      'reviewer_updates': [{
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1123814
                          },
                          'state': 'REVIEWER'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1149894
                          },
                          'state': 'REVIEWER'
                      }, {
                          'updated': '2024-05-21 23:21:04.000000000',
                          'updated_by': {
                              '_account_id': 1523797
                          },
                          'reviewer': {
                              '_account_id': 1308749
                          },
                          'state': 'REVIEWER'
                      }]
                  },
                  {
                      '_number': 78390,
                      'project': 'myproject',
                      'current_revision_number': 1,
                  },
              ],
          }, filtered_hosts={
              'chromium-review.googlesource.com': [1234],
              'chromium-internal-review.googlesource.com': [4560, 7890],
          }), api.post_process(DropExpectation))
