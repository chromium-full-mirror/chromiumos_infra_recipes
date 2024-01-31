# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cts_results_archive.cts_results_archive import \
  CTSResultsArchiveProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'cts_results_archive',
]



def RunSteps(api):
  api.cts_results_archive.archive('source_dir')


def GenTests(api):

  # Copied from test_runner.py
  def _set_build(bid, tags=None, swarming_tags=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    build_msg = api.buildbucket.ci_build_message(build_id=bid, tags=bb_tags,
                                                 project='chromeos',
                                                 bucket='test_runner',
                                                 builder='test_runner')
    if swarming_tags:
      build_msg.infra.swarming.bot_dimensions.extend(
          api.cros_tags.tags(**swarming_tags))

    return api.buildbucket.build(build_msg)

  yield api.test(
      'basic',
      _set_build(
          bid=42, tags={
              'build': 'fake-board-release/R11-123.45',
              'label-model': 'fake-model',
              'parent_task_id': 'deadbeef',
          }),
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl='gs://fake/results',
                      cts_apfe_gsurl='gs://fake/apfe',
                  )
          }))

  yield api.test(
      'missing-tag-build',
      _set_build(
          bid=42, tags={
              'label-image': 'fake-board-release/R11-123.45',
              'label-model': 'fake-model',
              'parent_task_id': 'deadbeef',
          }),
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl='gs://fake/results',
                      cts_apfe_gsurl='gs://fake/apfe',
                  )
          }))

  yield api.test(
      'missing-tag-label-model',
      _set_build(
          bid=42, tags={
              'label-image': 'fake-board-release/R11-123.45',
              'parent_task_id': 'deadbeef',
          }, swarming_tags={
              'label-model': 'fake-model',
          }),
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl='gs://fake/results',
                      cts_apfe_gsurl='gs://fake/apfe',
                  )
          }))

  yield api.test(
      'missing-tag-parent_task_id',
      _set_build(
          bid=42, tags={
              'build': 'fake-board-release/R11-123.45',
              'label-model': 'fake-model',
          }),
      api.properties(
          **{
              '$chromeos/cts_results_archive':
                  CTSResultsArchiveProperties(
                      cts_results_gsurl='gs://fake/results',
                      cts_apfe_gsurl='gs://fake/apfe',
                  )
          }))
