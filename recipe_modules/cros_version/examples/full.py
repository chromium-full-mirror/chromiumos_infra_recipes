# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_version.examples.test import TestInputProperties
from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/file',
    'git_footers',
    'cros_version',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):

  expected_version = properties.expected_version or 'R99-1234.56.0'
  expected_snapshot = (
      properties.expected_version_snapshot or
      api.cros_version.test_api.test_snapshot)
  v = api.cros_version.version
  api.assertions.assertEqual(v.chrome_branch, v.milestone)
  if not properties.remove_snapshot:
    api.assertions.assertEqual(
        str(v), '{}-{}'.format(expected_version, expected_snapshot))
  else:
    api.assertions.assertEqual(str(v), expected_version)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'internal-builder',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='atlas-cq'))

  yield api.test(
      'set-version', api.cros_version.workspace_version('R86-13421.11.0'),
      api.git_footers.simulated_get_footers(
          ['99'], 'read chromeos version.read snapshot'),
      api.properties(
          TestInputProperties(expected_version='R86-13421.11.0',
                              expected_version_snapshot='99')))

  yield api.test(
      'with-custom-snapshot',
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      snapshot_cas=CrosSourceProperties.SnapshotCas(
                          digest='hash!!!'),
                  )
          }),
      api.properties(TestInputProperties(expected_version_snapshot='hash!!!')),
  )

  yield api.test(
      'remove-snapshot',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True)
          }),
      api.properties(TestInputProperties(remove_snapshot=True)),
  )
