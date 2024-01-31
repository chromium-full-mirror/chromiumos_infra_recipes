# Copyright 2023 The ChromiumOS Authors
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



def RunSteps(api):
  api.git.cherry_pick_silent_fail('branch')
  api.git.cherry_pick_abort()


def GenTests(api):
  yield api.test(
      'success',
      api.post_process(post_process.MustRun, 'git cherry-pick'),
      api.post_process(post_process.MustRun, 'git cherry-pick --abort'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cherry-pick-fail',
      api.step_data('git cherry-pick', retcode=1),
      api.post_process(post_process.MustRun, 'git cherry-pick'),
      api.post_process(post_process.MustRun, 'git cherry-pick --abort'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'abort-fail',
      api.step_data('git cherry-pick --abort', retcode=1),
      api.post_process(post_process.MustRun, 'git cherry-pick'),
      api.post_process(post_process.MustRun, 'git cherry-pick --abort'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
