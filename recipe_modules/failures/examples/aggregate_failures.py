# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

def RunSteps(api):
  failures = []
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.SUCCESS)

  failures = [api.failures.Failure(kind='kind', title='title', fatal=False)]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.SUCCESS)

  failures = [
      api.failures.Failure(kind='build', title='build-a', fatal=True),
      api.failures.Failure(kind='build', title='build-b', fatal=True),
      api.failures.Failure(kind='test', title='test-a', fatal=True),
      api.failures.Failure(kind='test', title='test-b', fatal=False),
  ]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.FAILURE)
  api.assertions.assertEqual(
      result.summary_markdown,
      '''\
2 builds failed
- build-a
- build-b

1 test failed
- test-a''')

def GenTests(api):
  yield api.test('basic')
