# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cts_results_archive.cts_results_archive import \
  CTSResultsArchiveProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'cts_results_archive',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cts_results_archive.archive('source_dir')


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.build(
          api.buildbucket.ci_build_message(
              tags=api.cros_tags.tags(
                  **{
                      'build': 'fake-board-release/R11-123.45',
                      'label-model': 'fake-model',
                      'parent_task_id': 'deadbeef',
                  }))),
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl="gs://fake/results",
                      cts_apfe_gsurl="gs://fake/apfe",
                  )
          }))
