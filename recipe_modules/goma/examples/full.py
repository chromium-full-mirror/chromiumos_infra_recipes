# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Example to demonstrate usage of the goma module."""

from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.chromiumos import common
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
from PB.recipe_modules.chromeos.goma.examples.test import TestInputProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'goma',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  if properties.expected_goma_approach > common.GomaConfig.DEFAULT:
    api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  else:
    api.assertions.assertIsNone(api.goma.goma_dir)

  # Expectations should show it didn't fetch again.
  if properties.expected_goma_approach > common.GomaConfig.DEFAULT:
    api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  else:
    api.assertions.assertIsNone(api.goma.goma_dir)

  api.assertions.assertEqual(api.goma.goma_approach,
                             properties.expected_goma_approach)
  api.assertions.assertIsNone(
      api.goma.process_artifacts(InstallPackagesResponse(), 'goma_log_dir',
                                 'build_target'))
  # Call process_artifacts without goma_artifacts for prod and staging.
  api.assertions.assertIsNone(
      api.goma.process_artifacts(InstallPackagesResponse(),
                                 str(api.path.mkdtemp(prefix='goma-logs-')),
                                 'build_target'))
  api.assertions.assertIsNone(
      api.goma.process_artifacts(InstallPackagesResponse(),
                                 str(api.path.mkdtemp(prefix='goma-logs-')),
                                 'build_target', is_staging=True))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          TestInputProperties(
              expected_goma_approach=common.GomaConfig.RBE_CHROMEOS,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-goma-config',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      client_version='staging',
                      goma_approach=common.GomaConfig.RBE_STAGING,
                  )
          }),
      api.properties(
          TestInputProperties(
              expected_goma_approach=common.GomaConfig.RBE_STAGING,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-default-goma-config',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.DEFAULT,
                  ),
          }),
      api.properties(
          TestInputProperties(
              expected_goma_approach=common.GomaConfig.DEFAULT,
          ),
      ),
      api.post_process(post_process.DropExpectation),
  )
