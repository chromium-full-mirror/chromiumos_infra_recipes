# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.chromiumos.builder_config import BuilderConfig

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_artifacts',
    'cros_infra_config',
    'git_footers',
    'test_util',
]



def RunSteps(api):
  api.cros_infra_config.configure_builder()

  api.cros_artifacts.publish_latest_files('chromeos-image-archive',
                                          'eve-release')


def GenTests(api):
  yield api.test(
      'basic',
      api.test_util.test_child_build('eve', builder='eve-release-main',
                                     bucket='release').build,
      api.properties(
          **{'$chromeos/cros_version': {
              'remove_snapshot_from_version': True,
          }}),
      api.post_process(
          post_process.StepCommandContains,
          'write LATEST files.write "R99-1234.56.0" to tmp LATEST file',
          ['R99-1234.56.0']),
      api.step_data('write LATEST files.write LATEST-main.gsutil cat',
                    stdout=api.raw_io.output_text('R99-1234.55.0')))

  yield api.test(
      'newer-version',
      api.test_util.test_child_build('eve', builder='eve-release-main',
                                     bucket='release').build,
      api.properties(
          **{'$chromeos/cros_version': {
              'remove_snapshot_from_version': True,
          }}),
      api.post_process(
          post_process.StepCommandContains,
          'write LATEST files.write "R99-1234.56.0" to tmp LATEST file',
          ['R99-1234.56.0']),
      api.step_data('write LATEST files.write LATEST-main.gsutil cat',
                    stdout=api.raw_io.output_text('R99-1234.57.0')),
      api.post_check(
          post_process.DoesNotRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromeos-image-archive/eve-release/LATEST-main'
      ))

  yield api.test(
      'no-builder-config',
      api.post_check(post_process.StepFailure, 'write LATEST files'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  snapshot_config = BuilderConfig()
  snapshot_config.id.type = BuilderConfig.Id.SNAPSHOT
  yield api.test(
      'snapshot',
      api.properties(
          **{'$recipe_engine/led': {
              'led_run_id': '8989898989898989898',
          }}),
      api.cros_infra_config.use_custom_builder_config(
          snapshot_config, step_name='configure builder'),
      api.git_footers.simulated_get_footers(
          ['99999'], 'write LATEST files.read chromeos version.read snapshot'),
      api.git_footers.simulated_get_footers(
          ['1234567'], 'write LATEST files.read snapshot identifier'),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write "R99-1234.56.0-99999-8989898989898989898" to tmp LATEST file'
      ),
      api.post_check(post_process.MustRun,
                     'write LATEST files.write LATEST-1234.56.0'),
      api.post_check(post_process.MustRun,
                     'write LATEST files.write LATEST-SNAPSHOT-1234567'),
  )
