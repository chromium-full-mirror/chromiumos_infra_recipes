# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/raw_io',
    'git_txn',
]


def RunSteps(api):
  api.git_txn.update_ref(lambda: None)
  api.git_txn.update_ref(lambda: False)
  api.git_txn.update_ref_write_file('remote', 'Update file', 'file/path.txt',
                                    'data', ref='ref')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'update_ref_has_diff_has_change',
      api.step_data('git transaction (3).diff check.git ls-files', retcode=0),
      api.step_data('git transaction (3).diff check.git diff', retcode=1))
