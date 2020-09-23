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
from PB.recipe_modules.chromeos.cros_version.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  v = api.cros_version.Version(99, 1234, 56, 1, 2)
  api.assertions.assertEqual(str(v), 'R99-1234.56.1-2')
  api.assertions.assertEqual(v.buildspec_filename, '99/1234.56.1.xml')

  v = api.cros_version.read_workspace_version()
  api.assertions.assertEqual(
      str(v), 'R99-1234.56.0-' + properties.expected_version_snapshot)

  # The second read gets an empty file.
  api.assertions.assertRaises(ValueError,
                              api.cros_version.read_workspace_version)


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
