#  -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
    'src_state',
]


# TODO(crbug/1098567): Refactor this to be actual examples, and move the tests
# into tests/.


def RunSteps(api):
  remote = 'https://mygithost.google.com/somerepo'
  api.git.clone(remote)
  api.git.checkout('HEAD', branch='test')
  api.git.set_upstream(remote, 'test')


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.MustRun, 'git branch'))
