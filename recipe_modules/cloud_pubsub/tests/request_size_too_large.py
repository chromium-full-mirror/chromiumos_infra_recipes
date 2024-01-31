# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests the case where a request is larger than the Pub/Sub limit."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'cloud_pubsub',
]



def RunSteps(api):
  large_data = 'a' * int(1e+7 + 1)
  api.cloud_pubsub.publish_message(
      project_id='chromeos-bot', topic_id='analysis-service-events',
      data=large_data,
      raise_on_failed_publish=api.properties['raise_on_failed_publish'])


def GenTests(api):
  yield api.test(
      'fails-critical-publish',
      api.properties(raise_on_failed_publish=True),
      api.post_process(post_process.DoesNotRun,
                       'publish message.publish-message'),
      api.post_process(
          post_process.SummaryMarkdown,
          'data size (10000001) is > the Pub/Sub request limit (10000000)'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'passes-non-critical-publish',
      api.properties(raise_on_failed_publish=False),
      api.post_process(post_process.DoesNotRun,
                       'publish message.publish-message'),
      api.post_process(post_process.StepSuccess, 'publish message'),
      api.post_process(post_process.DropExpectation),
  )
