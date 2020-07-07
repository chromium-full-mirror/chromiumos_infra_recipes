# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'repo',
]


def RunSteps(api):
  infos = api.repo.project_infos(regexes=['some/bad/regex'])
  api.assertions.assertEqual(len(infos), 0)


def GenTests(api):
  # A regex that doesn't match anything (empty string in output) doesn't
  # cause an exception, but returns empty infos instead.
  yield api.test(
      'bad-regex',
      api.step_data('repo forall', stdout=api.raw_io.output('')),
  )
