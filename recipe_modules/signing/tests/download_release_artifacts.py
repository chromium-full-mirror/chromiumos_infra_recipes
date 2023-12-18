# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for download_release_artifacts."""

from PB.chromiumos.common import IMAGE_TYPE_RECOVERY

from PB.chromiumos.signing import SigningConfig
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import \
  CrosArtifactsProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  signing_configs = [
      SigningConfig(
          image_type=IMAGE_TYPE_RECOVERY,
          keyset='amd64-generic-foo-bar',
          ensure_no_password=True,
          firmware_update=True,
      )
  ]
  relevant_signing_configs, archive_dir = api.signing.download_release_artifacts(
      signing_configs)
  api.assertions.assertEqual(signing_configs, relevant_signing_configs)
  api.assertions.assertEqual(str(archive_dir), '[CLEANUP]/signing-dir_tmp_1')

  # Nothing configured for IMAGE_TYPE_UPDATE_PAYLOAD.
  with api.assertions.assertRaises(ValueError):
    _ = api.signing.get_paygen_keyset()


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.post_check(
          post_process.MustRun, 'download release artifacts.gsutil download '
          'recovery_image.tar.xz from chromeos-image-archive/'
          'amd64-generic-release/R99-1234.56.0-101'),
      # Don't duplicate downloads.
      api.post_check(
          post_process.DoesNotRun,
          'download release artifacts.gsutil download recovery_image.tar.xz from chromeos-image-archive/amd64-generic-release/R99-1234.56.0-101 (2)'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.build_menu.test(
      'missing-gs-file',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.step_data(
          'download release artifacts.gsutil download '
          'recovery_image.tar.xz from chromeos-image-archive/'
          'amd64-generic-release/R99-1234.56.0-101', retcode=1),
      api.post_process(post_process.DropExpectation),
  )
