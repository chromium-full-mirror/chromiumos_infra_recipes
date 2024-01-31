# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/properties',
    'cloud_pubsub',
]



def RunSteps(api):
  api.cloud_pubsub.publish_message(
      project_id='chromeos-bot', topic_id='analysis-service-events',
      data='Some test data',
      raise_on_failed_publish=api.properties['raise_on_failed_publish'])


def GenTests(api):

  def gimme_n_publish_failures(n):
    sd = api.step_data('publish message.publish-message', retcode=1)
    for x in range(n - 1):
      sd += api.step_data('publish message (%s).publish-message' % str(x + 2),
                          retcode=1)
    return sd

  yield api.test('fails-critical-publish',
                 status='INFRA_FAILURE') + api.properties(
                     raise_on_failed_publish=True) + gimme_n_publish_failures(3)

  # There won't be any exponential retries for a non critical publish.
  yield api.test('passes-non-critical-publish') + api.properties(
      raise_on_failed_publish=False) + gimme_n_publish_failures(0)
