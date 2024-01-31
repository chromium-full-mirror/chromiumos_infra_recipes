#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.post_process import MustRun, DoesNotRun

DEPS = [
    'recipe_engine/raw_io',
    'git',
]



def RunSteps(api):
  api.git.delete_local_branch('mybranch')


def GenTests(api):
  yield api.test(
      'delete-existing-branch',
      api.step_data(
          'git branch',
          stdout=api.raw_io.output_text('  main\n  mybranch\n* foo\n')),
      api.post_check(MustRun, 'git branch'),
      # git branch -D mybranch is not called
      api.post_check(MustRun, 'git branch -D mybranch'))

  yield api.test(
      'delete-non-existing-branch',
      api.step_data(
          'git branch',
          stdout=api.raw_io.output_text('  main\n  myotherbranch\n* foo\n')),
      api.post_check(MustRun, 'git branch'),
      # git branch -D mybranch is not called
      api.post_check(DoesNotRun, 'git branch -D mybranch'))
