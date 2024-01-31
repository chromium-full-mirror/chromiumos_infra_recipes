# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.chromiumos import common
from PB.chromiumos.common import GomaArtifacts
from PB.recipe_modules.chromeos.goma.goma import GomaProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'goma',
]



def RunSteps(api):
  gs_path = api.goma.process_artifacts(
      InstallPackagesResponse(goma_artifacts=GomaArtifacts()),
      str(api.path.mkdtemp(prefix='goma-logs-')), 'build_target')
  # Because disable_goma_logs_upload is set, the return value should be None
  # to indicate no logs were processed.
  api.assertions.assertEqual(gs_path, None)


def GenTests(api):
  yield api.test(
      'goma-config-property-disable',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      client_version='staging',
                      goma_approach=common.GomaConfig.RBE_STAGING,
                      disable_goma_logs_upload=True,
                      disable_stats_counterz_upload=True,
                  )
          }),
  )
