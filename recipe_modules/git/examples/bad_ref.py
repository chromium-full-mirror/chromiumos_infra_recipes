# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
    'src_state',
]



def RunSteps(api):
  revision = 'abcdef'
  api.assertions.assertFalse(api.git.is_reachable(revision))
  api.assertions.assertTrue(api.git.is_reachable(revision, head=revision))


def GenTests(api):
  sha1 = 'cce0727710f0c250357fddf1bf033e8300afb932'
  yield api.test(
      'basic',
      api.step_data(
          'git merge-base',
          retcode=2,
          stdout=api.raw_io.output(
              'fatal: Not a valid commit name {}'.format(sha1)),
      ),
  )
