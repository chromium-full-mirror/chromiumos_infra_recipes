#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git_cl',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  issue_map = api.git_cl.issues()
  api.assertions.assertEqual(issue_map['refs/heads/main'], '123123')
  api.assertions.assertEqual(issue_map['refs/heads/branch'], '456456')


def GenTests(api):
  yield api.test(
      'basic',
      api.git_cl.issues('', {
          'refs/heads/main': '123123',
          'refs/heads/branch': '456456'
      }))
