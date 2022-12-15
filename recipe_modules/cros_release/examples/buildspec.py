# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_menu',
    'build_reporting',
    'cros_release',
    'git',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_release.create_buildspec()
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='bucket/foo/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='gs://bucket/foo/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='bucket/foo/bar.xml')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.buildspec = ManifestLocation(manifest_gs_path='foo')
  api.assertions.assertEqual(api.cros_release.buildspec.manifest_gs_path, 'foo')


def GenTests(api):
  yield api.build_menu.test(
      'basic', api.git.diff_check(True),
      api.test_util.test_child_build('amd64-generic').build)

  yield api.build_menu.test('staging-build', api.git.diff_check(False),
                            api.test_util.test_child_build('staging-eve').build)
