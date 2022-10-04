# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  failures = []
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.SUCCESS)

  failures = [
      api.failures.Failure(kind='kind', title='title',
                           link_map={'title': 'url'}, fatal=False, id='my id'),
  ]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.SUCCESS)

  failures = [
      api.failures.Failure(kind='build', title='build-a',
                           link_map={'build page': 'build-a.com'}, fatal=True,
                           id='id-0'),
      api.failures.Failure(kind='build', title='build-b',
                           link_map={'build page': 'build-b.com'}, fatal=True,
                           id='id-1'),
      api.failures.Failure(kind='test', title='test-a',
                           link_map={'subtest-1': 'test-a.com'}, fatal=True,
                           id='id-2'),
      api.failures.Failure(kind='test', title='test-b',
                           link_map={'test-b': 'test-b.com'}, fatal=False,
                           id='id-3'),
  ]
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.FAILURE)
  api.assertions.assertEqual(
      result.summary_markdown, '''\
2 builds failed

- build-a: [build page](build-a.com)

- build-b: [build page](build-b.com)

1 test failed

- test-a: [subtest-1](test-a.com)''')

  failures = [
      api.failures.Failure(kind='build', title='build-a', link_map={
          'build page': 'build-a.com'
      }, fatal=True, id='my id'),
  ] * 50
  result = api.failures.aggregate_failures(failures)
  api.assertions.assertEqual(result.status, common_pb2.FAILURE)
  api.assertions.assertIn('40 others', result.summary_markdown)

  # Try to exceed the 4000 limit with really long test links.
  really_long_text = 'All code and no test makes failures a dull module.' * 4000
  failures = [
      api.failures.Failure(
          kind='test', title='test-a', link_map={
              'subtest-1': 'testlink.com',
              'subtest-2': really_long_text,
          }, fatal=True, id='id-3'),
  ]
  result = api.failures.aggregate_failures(failures)


def GenTests(api):
  yield api.test('basic')
