# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import StringPair

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_tags',
]


DEFAULT_VALUE = 'default-value'


def RunSteps(api):
  string_pairs = [
      StringPair(key=k, value=v) for (k, v) in api.properties['keyvals']
  ]
  actual_value = api.cros_tags.get_single_value(api.properties['check_key'],
                                                tags=string_pairs,
                                                default=DEFAULT_VALUE)
  api.assertions.assertEqual(actual_value, api.properties['expected_value'])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(keyvals=[('test-key', 'foo')], check_key='test-key',
                     expected_value='foo'),
  )

  yield api.test(
      'multiple-occurrences',
      api.properties(
          keyvals=[('key1', 'foo'), ('key2', 'bar'), ('key1', 'baz')],
          check_key='key1', expected_value='foo'),
  )

  yield api.test(
      'no-results',
      api.properties(
          keyvals=[('key1', 'foo'), ('key2', 'bar'), ('key1', 'baz')],
          check_key='not-present-key', expected_value=DEFAULT_VALUE),
  )
