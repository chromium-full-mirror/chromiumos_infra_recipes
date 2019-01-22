# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/json',
    'build_manager',
]

TEST_BUILD = {'id': 12345, 'update_time': '2019-01-01T10:00:20.021Z'}


def RunSteps(api):
  api.build_manager._buildbucket_batch(
      'failure_type', [{}], test_response={
          'responses': [{
              'error': {
                  'code': 99,
                  'message': 'failed'
              }
          }]
      })

  api.build_manager._buildbucket_batch('bad_response_count', [{}],
                                       test_response={'responses': []})

  m = api.build_manager.new_manager()
  m.poll()
  m.add_build('test_project/test_bucket/test_builder')
  m.schedule_builds(test_response=TEST_BUILD)
  m.poll()


def GenTests(api):
  yield api.test('basic')
