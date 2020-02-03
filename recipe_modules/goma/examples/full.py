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
  gs_path = api.goma.process_artifacts(
      InstallPackagesResponse(goma_artifacts=GomaArtifacts()),
      str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target')
  # Because the goma module uses recipe_engine/time rather than datetime,
  # during testing the self.m.time.utcnow() method will always return the same
  # date (2012/05/14).
  api.assertions.assertEqual(gs_path, '2012/05/14/build_target')

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
