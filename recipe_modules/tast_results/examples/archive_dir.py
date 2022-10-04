# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.tast_results.tast_results import TastResultsProperties

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'tast_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')
  api.tast_results.archive_dir(temp_dir, '1')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/tast_results':
                  TastResultsProperties(archive_gs_bucket='archive-bucket')
          }))
