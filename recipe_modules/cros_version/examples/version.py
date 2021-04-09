# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for api.cros_version.Version."""

DEPS = [
    'recipe_engine/assertions',
    'cros_version',
]


def RunSteps(api):
  v = api.cros_version.Version(99, 1234, 56, 1, 2)

  api.assertions.assertEqual(str(v), 'R99-1234.56.1-2')
  api.assertions.assertEqual(v.buildspec_filename, '99/1234.56.1.xml')

  v1 = api.cros_version.Version(99, 1234, 56, 1, 2)
  v1_2 = api.cros_version.Version(99, 1234, 56, 1, 2)
  v2 = api.cros_version.Version(98, 1235, 56, 1, 2)
  v3 = api.cros_version.Version(98, 1235, 57, 1, 2)
  v4 = api.cros_version.Version(98, 1235, 57, 2, 2)

  # Test the version comparisons.
  api.assertions.assertTrue(v1 < v2)
  api.assertions.assertTrue(v2 < v3)
  api.assertions.assertTrue(v3 < v4)
  api.assertions.assertTrue(v3 > v2)
  api.assertions.assertTrue(v2 > v1)
  api.assertions.assertTrue(v4 > v3)

  api.assertions.assertTrue(v1 == v1_2)

  # Test the parsing of arbitrary strings.
  v = api.cros_version.Version.from_string('134.1.2')
  api.assertions.assertEqual(v, api.cros_version.Version(None, 134, 1, 2, None))
  v = api.cros_version.Version.from_string('R1000-134.1.2')
  api.assertions.assertEqual(v, api.cros_version.Version(1000, 134, 1, 2, None))
  # Close but not a real version.
  v = api.cros_version.Version.from_string('1213.123.41.21')
  api.assertions.assertIsNone(v)

  # Test the is_after method.
  v = api.cros_version.Version.from_string('R90-134.1.2')
  api.assertions.assertTrue(v.is_after(v))
  api.assertions.assertTrue(v.is_after('134.1.2'))
  api.assertions.assertFalse(v.is_after('134.1.3'))
  api.assertions.assertFalse(v.is_after('135.0.0'))


def GenTests(api):
  yield api.test('basic')
