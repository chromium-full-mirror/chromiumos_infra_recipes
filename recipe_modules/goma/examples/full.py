# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'goma',
]

from PB.chromiumos import common

from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.chromiumos.common import GomaArtifacts
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
from PB.recipe_modules.chromeos.goma.examples.test import TestInputProperties

PROPERTIES = TestInputProperties

def RunSteps(api, properties):
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')

  # Expectations should show it didn't fetch again.
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')
  api.assertions.assertEqual(
      str(api.goma.goma_client_json),
      '/creds/service_accounts/service-account-goma-client.json');
  api.assertions.assertEqual(
      api.goma.goma_approach,
      properties.expected_goma_approach)
  api.assertions.assertEqual(
      api.goma.process_artifacts(
          InstallPackagesResponse(), 'goma_log_dir', 'build_target'), None)
  # Call process_artifacts without goma_artifacts for prod and staging.
  api.assertions.assertEqual(
      api.goma.process_artifacts(
          InstallPackagesResponse(),
          str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target'),
      None)
  api.assertions.assertEqual(
      api.goma.process_artifacts(
          InstallPackagesResponse(),
              str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target',
          is_staging=True),
      None)

def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(TestInputProperties(
             expected_goma_approach=common.GomaConfig.DEFAULT,
         )))

  yield (api.test('with-goma-config') +  #
         api.properties(
             **{'$chromeos/goma':
                GomaProperties(
                    client_version='staging',
                    goma_approach=common.GomaConfig.RBE_STAGING,
                )}) +  #
         api.properties(TestInputProperties(
             expected_goma_approach=common.GomaConfig.RBE_STAGING,
         )))
