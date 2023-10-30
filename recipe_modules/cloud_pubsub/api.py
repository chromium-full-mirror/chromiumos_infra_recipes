# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for using Cloud Pub/Sub"""

import datetime
import pprint

from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry


class CloudPubsubApi(recipe_api.RecipeApi):
  """A module for Cloud Pub/Sub"""

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def publish_message(self, project_id, topic_id, data, ordering_key=None,
                      endpoint=None, raise_on_failed_publish=True):
    """Publish a message to Cloud Pub/Sub

    When specifying an ordering key to ensure message ordering, an explicit
    endpoint needs to be specified, and only messages going through the same
    endpoint are guaranteed to be ordered.

    Args:
      * project_id (str): The project name.
      * topic_id (str): The topic name.
      * data (str): The data to put in the message. The input must be encodable
        with utf8, as it will be sent to the publish-message binary via JSON.
      * ordering_key (str): ordering key to be sent with message
      * endpoint (str): specific pub/sub endpoint to use
          eg: "us-east1-pubsub.googleapis.com"
      * raise_on_failed_publish (bool): If True, raise exception on failure.

    Raises:
      InfraFailure: If the publish fails and raise_on_failed_publish.
    """
    with self.m.step.nest('publish message') as presentation,\
         self.m.context(infra_steps=True):

      publish_input = {
          'project_id': project_id,
          'topic_id': topic_id,
          'data': data,
          'ordering_key': ordering_key or '',
          'endpoint': endpoint or '',
      }

      presentation.logs['request'] = pprint.pformat(publish_input)

      test_output_data = {'message_id': '12345'}
      try:
        self.m.support.call('publish-message', publish_input, infra_step=True,
                            test_output_data=test_output_data)
      except recipe_api.InfraFailure as e:
        if raise_on_failed_publish:
          raise e
        presentation.step_text = 'Failed but not fatal.'
        presentation.status = self.m.step.INFRA_FAILURE
