# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for disabling/enabling pubsub update"""

from PB.chromiumos.build_report import BuildReport
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_reporting',
]


def RunSteps(api):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')

  with api.step.nest('without pubsub'):
    api.build_reporting.disable_pubsub = True
    with api.build_reporting.publish_to_gs():
      api.build_reporting.publish_status(BuildReport.BuildStatus.RUNNING)

  with api.step.nest('with pubsub'):
    api.build_reporting.disable_pubsub = False
    with api.build_reporting.publish_to_gs():
      api.build_reporting.publish_status(BuildReport.BuildStatus.RUNNING)


def GenTests(api):
  yield api.test(
      'basic',
      # With enabling pubsub, confirms the empty step_text.
      api.post_check(post_process.MustRun,
                     'with pubsub.build status pubsub update'),
      api.post_check(post_process.MustRun,
                     'with pubsub.Enabling the pubsub publication.'),
      api.post_process(
          post_process.StepTextEquals,
          'with pubsub.build status pubsub update',
          '',
      ),
      # With disabling pubsub, confirms the step_text of skipping pubsub.
      api.post_check(post_process.MustRun,
                     'without pubsub.build status pubsub update'),
      api.post_check(post_process.MustRun,
                     'without pubsub.Disabling the pubsub publication.'),
      api.post_process(
          post_process.StepTextEquals,
          'without pubsub.build status pubsub update',
          'Skipping pubsub update for configuration.',
      ),
  )
