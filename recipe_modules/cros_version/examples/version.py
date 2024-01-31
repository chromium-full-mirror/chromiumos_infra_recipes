# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for api.cros_version.Version."""

DEPS = [
    'recipe_engine/assertions',
    'cros_version',
]



def RunSteps(api):
  version = api.cros_version.Version
  v = version(99, 1234, 56, 1, 2)

  api.assertions.assertEqual(str(v), 'R99-1234.56.1-2')
  api.assertions.assertEqual(v.buildspec_filename, '99/1234.56.1.xml')

  v1 = version(99, 1234, 56, 1, 2)
  v1_2 = version(99, 1234, 56, 1, 2)
  v2 = version(98, 1235, 56, 1, 2)
  v3 = version(98, 1235, 57, 1, 2)
  v4 = version(98, 1235, 57, 2, 2)

  # Test the version comparisons.
  api.assertions.assertTrue(v1 < v2)
  api.assertions.assertTrue(v2 < v3)
  api.assertions.assertTrue(v3 < v4)
  api.assertions.assertTrue(v3 > v2)
  api.assertions.assertTrue(v2 > v1)
  api.assertions.assertTrue(v4 > v3)

  api.assertions.assertTrue(v1 == v1_2)

  # Test the parsing of arbitrary strings.
  v = version.from_string('134.1.2')
  api.assertions.assertEqual(v, version(None, 134, 1, 2, None))
  v = version.from_string('R1000-134.1.2')
  api.assertions.assertEqual(v, version(1000, 134, 1, 2, None))
  # Close but not a real version.
  v = version.from_string('1213.123.41.21')
  api.assertions.assertIsNone(v)

  # Test the is_after method.
  v = version.from_string('R90-134.1.2')
  api.assertions.assertTrue(v.is_after(v))
  api.assertions.assertTrue(v.is_after('134.1.2'))
  api.assertions.assertFalse(v.is_after('134.1.3'))
  api.assertions.assertFalse(v.is_after('135.0.0'))

  # Test from_branch_name.
  api.assertions.assertIsNone(version.from_branch_name('foo-86-R86.13421.B'))
  v = version.from_branch_name('release-R86-13421.B')
  api.assertions.assertEqual(v, version(86, 13421, 0, 0, None))
  v = version.from_branch_name('release-R86-13421.B-chromeos')
  api.assertions.assertEqual(v, version(86, 13421, 0, 0, None))
  v = version.from_branch_name('stabilize-123.B')
  api.assertions.assertEqual(v, version(None, 123, 0, 0, None))
  v = version.from_branch_name('stabilize-foo-123.B')
  api.assertions.assertEqual(v, version(None, 123, 0, 0, None))
  v = version.from_branch_name('stabilize-foo-123.456.B')
  api.assertions.assertEqual(v, version(None, 123, 456, 0, None))


def GenTests(api):
  yield api.test('basic')
