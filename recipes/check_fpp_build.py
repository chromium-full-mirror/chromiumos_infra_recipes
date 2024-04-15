# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to check fpp builds."""

DEPS = [
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  api.step('Clone source', [
      'git', 'clone', '--recurse-submodules', 'sso://nearby/fp-provider',
      str(api.path.cleanup_dir.join('fp-provider'))
  ])
  api.step('Build/Run tests', [
      str(api.path.cleanup_dir.join('fp-provider', 'build.sh')), 'gLinux',
      'run_tests'
  ])


def GenTests(api):
  yield api.test('build_test_fpp')
