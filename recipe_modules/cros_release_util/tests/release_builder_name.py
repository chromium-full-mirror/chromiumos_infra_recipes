# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_release_util',
    'cros_source',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'build_target':
        Property(
            kind=str,
            help='Name of the build target.',
            default=None,
        ),
    'is_staging':
        Property(
            kind=bool,
            help='Whether environment is staging.',
            default=False,
        ),
    'branch_name':
        Property(
            kind=str,
            help='Name of the builder branch.',
            default='main',
        ),
    'expected_builder_name':
        Property(kind=str, help='Expected name of the builder.', default=None)
}


def RunSteps(api, build_target, is_staging, branch_name, expected_builder_name):
  api.cros_source.test_api.manifest_branch = branch_name
  builder_name = api.cros_release_util.release_builder_name(
      build_target, branch_name, is_staging)
  api.assertions.assertEqual(expected_builder_name, builder_name)


def GenTests(api):
  yield api.test(
      'zork',
      api.properties(build_target='zork',
                     expected_builder_name='zork-release-main'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'staging-zork',
      api.properties(build_target='zork', is_staging=True,
                     expected_builder_name='staging-zork-release-main'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'zork-R98',
      api.properties(build_target='zork', branch_name='release-R98-14388.B',
                     expected_builder_name='zork-release-R98-14388.B'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'zork-tracking-snapshot',
      api.properties(build_target='zork', branch_name='snapshot',
                     expected_builder_name='zork-release-main'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'staging-zork-tracking-snapshot',
      api.properties(build_target='zork', is_staging=True,
                     branch_name='staging-snapshot',
                     expected_builder_name='staging-zork-release-main'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
