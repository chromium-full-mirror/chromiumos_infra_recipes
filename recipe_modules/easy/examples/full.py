# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'easy',
]


def RunSteps(api):
  api.easy.step('passthru', ['cat'], ok_ret=(0, 1))

  stdout = api.easy.stdout_step('raw', ['gzip'], stdin_data='uncompressed',
                                   test_stdout=lambda: 'compressed')
  assert stdout == 'compressed'

  json_stdout = api.easy.stdout_json_step('json', ['jq'], stdin_json={'a': 1},
                                   test_stdout={'b': 2})
  assert json_stdout == {'b': 2}

def GenTests(api):
  yield api.test('basic')
