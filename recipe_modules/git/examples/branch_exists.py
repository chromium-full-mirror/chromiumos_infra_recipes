#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'git',
]



def RunSteps(api):
  api.assertions.assertTrue(api.git.branch_exists('mybranch'))


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'git branch',
          stdout=api.raw_io.output_text('  main\n* mybranch\n  foo\n')),
  )
