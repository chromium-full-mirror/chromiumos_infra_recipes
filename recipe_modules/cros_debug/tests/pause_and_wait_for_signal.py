# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the signing recipe module."""

from PB.recipe_modules.chromeos.cros_debug.tests.pause_and_wait_for_signal import \
  PauseAndWaitForSignalProperties

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


PROPERTIES = PauseAndWaitForSignalProperties


def RunSteps(api, properties):
  path = api.path.mkdtemp()
  if properties.exists:
    api.path.mock_add_paths(path.join('resume'))
  api.cros_debug.pause_and_wait_for_signal(
      timeout=10, override_led_launch_only_staging=properties.override,
      test_location_override=path)


def GenTests(api):

  yield api.test(
      'file-exists',
      api.buildbucket.generic_build(build_id=0, bucket='staging'),
      api.properties(exists=True),
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

  yield api.test(
      'file-does-not-exist',
      api.properties(location='/tmp/foo/bar'),
      api.buildbucket.generic_build(build_id=0, bucket='staging'),
      api.properties(exists=False),
      api.post_process(post_process.MustRun,
                       'debug builder steps.set up file to watch'),
      api.post_process(post_process.StepTextContains,
                       'debug builder steps.set up file to watch',
                       ['Watching for file to appear to resume build']),
      api.post_process(post_process.MustRun,
                       'debug builder steps.waiting for file to appear'),
      api.post_process(post_process.MustRun, 'debug builder steps.clean up'),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.clean up.remove resume file'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'skips-in-prod',
      api.buildbucket.generic_build(build_id=0, bucket='prod'),
      api.post_process(
          post_process.StepTextEquals, 'debug builder steps',
          'Skipping debug steps as this is not a led launch or it is running outside of staging. Please either remove `cros_debug` from this recipe, or pass in the override flag if you really must run this this way.'
      ),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.set up file to watch'),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.waiting for file to appear'),
      api.post_process(post_process.DoesNotRun, 'debug builder steps.clean up'),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.clean up.remove resume file'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'skips-in-not-led',
      api.buildbucket.generic_build(bucket='staging'),
      api.post_process(
          post_process.StepTextEquals, 'debug builder steps',
          'Skipping debug steps as this is not a led launch or it is running outside of staging. Please either remove `cros_debug` from this recipe, or pass in the override flag if you really must run this this way.'
      ),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.set up file to watch'),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.waiting for file to appear'),
      api.post_process(post_process.DoesNotRun, 'debug builder steps.clean up'),
      api.post_process(post_process.DoesNotRun,
                       'debug builder steps.clean up.remove resume file'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'override-flag-overrides-non-led',
      api.buildbucket.generic_build(bucket='staging'),
      api.properties(exists=True, override=True),
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

  yield api.test(
      'override-flag-overrides-non-prod',
      api.buildbucket.generic_build(build_id=0, bucket='prod'),
      api.properties(exists=True, override=True),
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
