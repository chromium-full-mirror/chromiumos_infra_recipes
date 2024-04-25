# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the signing recipe module."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_debug',
]



def RunSteps(api):
  path = api.path.mkdtemp()
  api.path.mock_add_paths(path / 'resume')
  api.cros_debug.pause_and_wait_for_signal(timeout=6 * 60 * 600,
                                           test_location_override=path)


def GenTests(api):

  yield api.test(
      'timeout-capped',
      api.buildbucket.generic_build(build_id=0, bucket='staging'),
      api.post_process(
          post_process.StepTextEquals, 'debug builder steps',
          'Timeout specified is outside valid range, capping at 4 hours.'),
      api.post_process(post_process.MustRun,
                       'debug builder steps.set up file to watch'),
      api.post_process(post_process.StepTextContains,
                       'debug builder steps.set up file to watch',
                       ['Watching for file to appear to resume build']),
      api.post_process(post_process.MustRun,
                       'debug builder steps.waiting for file to appear'),
      api.post_process(post_process.StepTextEquals,
                       'debug builder steps.waiting for file to appear',
                       'found file, done sleeping'),
      api.post_process(post_process.MustRun, 'debug builder steps.clean up'),
      api.post_process(post_process.MustRun,
                       'debug builder steps.clean up.remove resume file'),
      api.post_process(post_process.DropExpectation),
  )
