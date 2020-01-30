# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'tast_results',
]


def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')
  response = api.tast_results.get_results(temp_dir, 'fancy-suite')
  api.tast_results.print_results(response, temp_dir)


def GenTests(api):
  yield api.test('basic')
