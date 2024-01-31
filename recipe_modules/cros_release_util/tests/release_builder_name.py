# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_release_util.tests.release_builder_name import \
  ReleaseBuilderNameProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_release_util',
    'cros_source',
]


PROPERTIES = ReleaseBuilderNameProperties


def RunSteps(api, properties):
  branch_name = properties.branch_name or 'main'

  api.cros_source.test_api.manifest_branch = branch_name
  builder_name = api.cros_release_util.release_builder_name(
      properties.build_target, branch_name, properties.is_staging)
  api.assertions.assertEqual(properties.expected_builder_name, builder_name)


def GenTests(api):
  yield api.test(
      'zork',
      api.properties(build_target='zork',
                     expected_builder_name='zork-release-main'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'staging-zork',
      api.properties(build_target='zork', is_staging=True,
                     expected_builder_name='staging-zork-release-main'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'zork-R98',
      api.properties(build_target='zork', branch_name='release-R98-14388.B',
                     expected_builder_name='zork-release-R98-14388.B'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'zork-tracking-snapshot',
      api.properties(build_target='zork', branch_name='snapshot',
                     expected_builder_name='zork-release-main'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'staging-zork-tracking-snapshot',
      api.properties(build_target='zork', is_staging=True,
                     branch_name='staging-snapshot',
                     expected_builder_name='staging-zork-release-main'),
      api.post_process(post_process.DropExpectation))
