#  -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'git',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.assertions.assertTrue(api.git.branch_exists('mybranch'))


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('git branch',
                    stdout=api.raw_io.output('  main\n* mybranch\n  foo\n')),
  )
