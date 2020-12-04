# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cts_results_archive.cts_results_archive import \
  CTSResultsArchiveProperties

DEPS = [
    'recipe_engine/properties',
    'cts_results_archive',
]


def RunSteps(api):
  api.cts_results_archive.archive('source_dir')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl="gs://fake/results",
                      cts_apfe_gsurl="gs://fake/apfe",
                  )
          }))
