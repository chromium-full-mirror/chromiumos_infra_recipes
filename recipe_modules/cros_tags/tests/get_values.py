# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.swarming.proto.api.swarming import StringPair

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_tags',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = {
    'keyvals':
        Property(
            help='Tuples of (key: str, value: str) to interpret as CrOS tags.'),
    'check_key':
        Property(help='Key to check in get_values.'),
    'expected_values':
        Property(help='List that get_values should return.')
}

DEFAULT_VALUE = 'default-value'


def RunSteps(api, keyvals, check_key, expected_values):
  string_pairs = [StringPair(key=k, value=v) for (k, v) in keyvals]
  actual_values = api.cros_tags.get_values(check_key, tags=string_pairs,
                                           default=DEFAULT_VALUE)
  api.assertions.assertEqual(actual_values, expected_values)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(keyvals=[('test-key', 'foo')], check_key='test-key',
                     expected_values=['foo']),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'multiple-results',
      api.properties(
          keyvals=[('key1', 'foo'), ('key2', 'bar'), ('key1', 'baz')],
          check_key='key1', expected_values=['foo', 'baz']),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'no-results',
      api.properties(
          keyvals=[('key1', 'foo'), ('key2', 'bar'), ('key1', 'baz')],
          check_key='not-present-key', expected_values=[DEFAULT_VALUE]),
      api.post_check(post_process.StatusSuccess))
