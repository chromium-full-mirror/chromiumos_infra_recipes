# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the cls with reviewers functionality."""

from recipe_engine.post_process import DropExpectation
from RECIPE_MODULES.chromeos.auto_runner_util.api import EnhancedChangeInfo

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'auto_runner_util',
]

def RunSteps(api):
  change_infos = api.properties['change_infos']
  enhancedcis = []
  for host, cis in change_infos.items():
    enhancedcis.extend(
        [EnhancedChangeInfo(c, host, api.auto_runner_util.m) for c in cis])
  actual = {c for c in enhancedcis if c.has_reviewers()}
  expected = api.properties['filtered_changes']
  api.assertions.assertTrue(actual == expected)

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
          }, filtered_changes={
              EnhancedChangeInfo({
                  '_number': 1234,
                  'project': 'myproject'
              }, 'chromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 4560,
                  'project': 'myproject'
              }, 'chromium-internal-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 7890,
                  'project': 'myproject'
              }, 'chromium-internal-review.googlesource.com', None),
          }), api.post_process(DropExpectation))
