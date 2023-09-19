# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.chromiumos import common
from PB.chromiumos.common import GomaArtifacts
from PB.recipe_modules.chromeos.goma.examples.test import TestInputProperties
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
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
  gs_tuple = api.goma.process_artifacts(
      InstallPackagesResponse(
          goma_artifacts=GomaArtifacts(
              counterz_file='counterz.binaryproto',
              stats_file='stats.binaryproto', log_files=[
                  'compiler_proxy-subproc.chromeos-ci.log.INFO.20200131.84.gz',
                  'compiler_proxy.chromeos-ci.log.INFO.20200131-063322.81.gz',
                  'gomacc.chromeos-ci.log.INFO.20200131-073921.1717.tar.gz',
                  'ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005.8.gz'
              ])), str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target')
  # Because the goma module uses recipe_engine/time rather than datetime,
  # during testing the self.m.time.utcnow() method will always return the same
  # date (2012/05/14).
  api.assertions.assertEqual(gs_tuple.path, '2012/05/14/build_target')
  api.assertions.assertEqual(gs_tuple.bucket, 'chrome-goma-log')
  # Verify for staging.
  staging_tuple = api.goma.process_artifacts(
      InstallPackagesResponse(
          goma_artifacts=GomaArtifacts(
              counterz_file='counterz.binaryproto',
              stats_file='stats.binaryproto', log_files=[
                  'compiler_proxy-subproc.chromeos-ci.log.INFO.20200131.84.gz',
                  'compiler_proxy.chromeos-ci.log.INFO.20200131-063322.81.gz',
                  'gomacc.chromeos-ci.log.INFO.20200131-073921.1717.tar.gz',
                  'ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005.8.gz'
              ])), str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target',
      is_staging=True)
  # Because the goma module uses recipe_engine/time rather than datetime,
  # during testing the self.m.time.utcnow() method will always return the same
  # date (2012/05/14).
  api.assertions.assertEqual(staging_tuple.path, '2012/05/14/build_target')
  api.assertions.assertEqual(staging_tuple.bucket, 'staging-chrome-goma-log')


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
                      bigquery_verbose=True,
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
