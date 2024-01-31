#  -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_account_id function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]



def RunSteps(api):
  account_id_1 = api.gerrit.get_account_id('test@test.com',
                                           'mygithost.google.com')
  # Call twice to test the caching.
  account_id_2 = api.gerrit.get_account_id('test@test.com',
                                           'mygithost.google.com')
  api.assertions.assertEqual(1234, account_id_1)
  api.assertions.assertEqual(account_id_1, account_id_2)


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.set_get_account_id(gerrit_host='mygithost.google.com',
                                    email='test@test.com', value=1234),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/accounts/test@test.com'),
      api.post_process(
          post_process.DoesNotRun,
          'curl https://mygithost.google.com/accounts/test@test.com (2)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'passed-on-retry',
      api.step_data('curl https://mygithost.google.com/accounts/test@test.com',
                    retcode=1),
      api.gerrit.set_get_account_id(gerrit_host='mygithost.google.com',
                                    email='test@test.com', value=1234,
                                    iteration=2),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/accounts/test@test.com (2)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'field-unset',
      api.gerrit.set_get_account_id(gerrit_host='mygithost.google.com',
                                    email='test@test.com', value=None),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/accounts/test@test.com'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
