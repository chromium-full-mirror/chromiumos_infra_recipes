# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
    'urls',
]

def RunSteps(api):
  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(api.urls.get_build_url(build),
                             api.buildbucket.build_url(build_id=123))

  skylab_task = api.skylab.test_api.skylab_task(url='skylab.whatever')
  api.assertions.assertEqual(api.urls.get_skylab_task_url(skylab_task),
                             'skylab.whatever')

  skylab_result = api.skylab.test_api.skylab_result(task=skylab_task)
  api.assertions.assertEqual(api.urls.get_skylab_result_url(skylab_result),
                             'skylab.whatever')

  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://bucket/a/b/c'),
      'https://storage.cloud.google.com/bucket/a/b/c')
  api.assertions.assertRaises(ValueError, api.urls.get_gs_path_url, 'a/b/c')


def GenTests(api):
  yield api.test('basic')
