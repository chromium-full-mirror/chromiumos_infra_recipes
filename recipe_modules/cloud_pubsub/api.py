# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for using Cloud Pub/Sub"""

import datetime

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.util.util import exponential_retry


class CloudPubsubApi(recipe_api.RecipeApi):
  """A module for Cloud Pub/Sub"""

  @exponential_retry(retries=3, delay=datetime.timedelta(minutes=2))
  def publish_message(self, project_id, topic_id, data):
    """Publish a message to Cloud Pub/Sub

    Args:
      * project_id (str): The project name.
      * topic_id (str): The topic name.
      * data (str): The data to put in the message. The input must be encodable
        with utf8, as it will be sent to the publish-message binary via JSON.
    """
    with self.m.step.nest('publish message'), self.m.context(infra_steps=True):
      input = {
          'project_id': project_id,
          'topic_id': topic_id,
          'data': data,
      }
      test_output_data = {'message_id': '12345'}
      self.m.support.call('publish-message', input,
                          test_output_data=test_output_data)
