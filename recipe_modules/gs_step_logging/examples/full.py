# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'gs_step_logging',
    'recipe_engine/step',
    'recipe_engine/raw_io',
]



def RunSteps(api):
  with api.step.nest('nested step'), api.gs_step_logging.log_step_to_gs(
      'testbucket/testprefix'):
    api.step(
        'basic with stdout',
        cmd=['echo', 'hello world'],
        stdout=api.raw_io.output(),
    )


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'nested step.basic with stdout',
          stdout=api.raw_io.output('Test stdout'),
      ),
      # Check that a copy to GS was done.
      api.post_process(
          post_process.MustRunRE,
          r'.*gsutil cp',
          at_most=1,
      ),
  )

  yield api.test(
      'failed_step',
      api.step_data(
          'nested step.basic with stdout',
          stdout=api.raw_io.output('Test stdout'),
          retcode=1,
      ),
      # Check that a copy to GS was done.
      api.post_process(
          post_process.MustRunRE,
          r'.*gsutil cp',
          at_most=1,
      ),
      api.post_process(post_process.DropExpectation),
      # Recipe should still fail.
      status='FAILURE',
  )
