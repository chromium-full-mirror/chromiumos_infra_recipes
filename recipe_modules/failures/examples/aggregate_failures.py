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

  failures = [
      api.failures.Failure(kind='kind', title='title', url='url', fatal=False),
  ]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.SUCCESS)

  failures = [
      api.failures.Failure(kind='build', title='build-a', url='build-a.com',
                           fatal=True),
      api.failures.Failure(kind='build', title='build-b', url='build-b.com',
                           fatal=True),
      api.failures.Failure(kind='test', title='test-a', url='test-a.com',
                           fatal=True),
      api.failures.Failure(kind='test', title='test-b', url='test-b.com',
                           fatal=False),
  ]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.FAILURE)
  api.assertions.assertEqual(
      result.summary_markdown, '''\
2 builds failed

- [build-a](build-a.com)

- [build-b](build-b.com)

1 test failed

- [test-a](test-a.com)''')

  failures = [
      api.failures.Failure(kind='build', title='build-a', url='build-a.com',
                           fatal=True),
  ] * 50
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.FAILURE)
  api.assertions.assertIn('40 others', result.summary_markdown)

def GenTests(api):
  yield api.test('basic')
