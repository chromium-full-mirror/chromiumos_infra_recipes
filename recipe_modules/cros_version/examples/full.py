# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/file',
    'cros_version',
]

from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_version.cros_version import (
    CrosVersionProperties)
from PB.recipe_modules.chromeos.cros_version.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  v = api.cros_version.Version(99, 1234, 56, 1, 2)

  api.assertions.assertEqual(str(v), 'R99-1234.56.1-2')
  api.assertions.assertEqual(v.buildspec_filename, '99/1234.56.1.xml')

  v = api.cros_version.read_workspace_version()
  if properties.expected_version_snapshot:
    api.assertions.assertEqual(
        str(v), 'R99-1234.56.0-' + properties.expected_version_snapshot)
  else:
    api.assertions.assertEqual(str(v), 'R99-1234.56.0')

  # The second read gets an empty file.
  api.assertions.assertRaises(ValueError,
                              api.cros_version.read_workspace_version)

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
  api.assertions.assertTrue(v == None)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('read chromeos version (2).read chromeos_version.sh',
                    api.file.read_raw('')),
      api.properties(TestInputProperties(expected_version_snapshot='101')),
  )

  yield api.test(
      'internal-builder',
      api.buildbucket.ci_build(builder='atlas-cq'),
      api.step_data('read chromeos version (2).read chromeos_version.sh',
                    api.file.read_raw('')),
      api.properties(TestInputProperties(expected_version_snapshot='101')),
  )

  yield api.test(
      'with-custom-snapshot',
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                          isolated_hash='hash!!!', isolate_server='server.com'),
                  )
          }),
      api.step_data('read chromeos version (2).read chromeos_version.sh',
                    api.file.read_raw('')),
      api.properties(TestInputProperties(expected_version_snapshot='hash!!!')),
  )

  yield api.test(
      'remove-snapshot',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True)
          }),
      api.step_data('read chromeos version (2).read chromeos_version.sh',
                    api.file.read_raw('')),
  )
