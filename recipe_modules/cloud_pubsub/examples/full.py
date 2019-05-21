# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['cloud_pubsub']


def RunSteps(api):
  api.cloud_pubsub.publish_message(project_id='chromeos-bot',
                                   topic_id='analysis-service-events',
                                   data='Some test data')


def GenTests(api):
  yield api.test('basic')
