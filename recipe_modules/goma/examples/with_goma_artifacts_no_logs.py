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
  # TODO(crbug.com/1041899): Update this comment when this test value indicates
  # that it did something. Right now there is a return value indicating a path
  # and bucket even though we are not yet handling stats and counterz and no
  # logs were processed (since the goma_artifacts did not contain any).
  gs_tuple = api.goma.process_artifacts(
      InstallPackagesResponse(
          goma_artifacts=GomaArtifacts(counterz_file='counterz.binaryproto',
                                       stats_file='stats.binaryproto')),
      str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target')
  # Because the goma module uses recipe_engine/time rather than datetime,
  # during testing the self.m.time.utcnow() method will always return the same
  # date (2012/05/14).
  api.assertions.assertEqual(gs_tuple.path, '2012/05/14/build_target')
  api.assertions.assertEqual(gs_tuple.bucket, 'chrome-goma-log')


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
