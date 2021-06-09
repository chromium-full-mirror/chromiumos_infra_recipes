# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
    'src_state',
]


def RunSteps(api):
  commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
  remote = 'https://mygithost.google.com/somerepo'
  api.assertions.assertFalse(api.git.is_reachable("abcdef"))


def GenTests(api):
  sha1 = 'cce0727710f0c250357fddf1bf033e8300afb932'
  yield api.test(
      'basic',
      api.step_data(
          "git merge-base",
          retcode=2,
          stdout=api.raw_io.output(
              'fatal: Not a valid commit name {}'.format(sha1)),
      ),
  )
