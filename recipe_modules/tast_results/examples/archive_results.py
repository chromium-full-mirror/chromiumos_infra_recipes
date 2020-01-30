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
  api.tast_results.archive_results(temp_dir, 'chromeos-archive')


def GenTests(api):
  yield api.test('basic')
