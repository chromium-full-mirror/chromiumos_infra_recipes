# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the is_green_for_local function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_tags',
    'greenness',
    'test_util',
]


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          builder='eve-kernelnext-snapshot', build_target_name='eve-kernelnext',
          critical='YES', status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          builder='eve-snapshot', build_target_name='eve', critical='YES',
          status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          builder='amd64-generic-bazel-snapshot',
          build_target_name='amd64-generic', critical='YES', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
  ]
  if api.properties['test_failed_builds']:
    for build in builds:
      build.status = 20

  api.greenness.update_build_info(builds)

  api.assertions.assertEqual(
      api.greenness.is_green_for_local(is_bazel=api.properties['is_bazel']),
      api.properties['expected_is_green_for_local'])


def GenTests(api):

  yield api.test(
      'is-green-for-local',
      api.properties(
          **{
              '$chromeos/greenness': {
                  'publish_property': True,
                  'llfg_exclude_variants': ['-kernelnext'],
              }
          }, test_failed_builds=False, is_bazel=False,
          expected_is_green_for_local=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'is-not-green-for-local',
      api.properties(
          **{
              '$chromeos/greenness': {
                  'publish_property': True,
                  'llfg_exclude_variants': ['-kernelnext'],
              }
          }, test_failed_builds=True, is_bazel=False,
          expected_is_green_for_local=False),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'is-green-for-local-bazel',
      api.properties(
          **{
              '$chromeos/greenness': {
                  'publish_property': True,
                  'llfg_exclude_variants': ['-kernelnext'],
              }
          }, test_failed_builds=False, is_bazel=True,
          expected_is_green_for_local=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'is-not-green-for-local-bazel',
      api.properties(
          **{
              '$chromeos/greenness': {
                  'publish_property': True,
                  'llfg_exclude_variants': ['-kernelnext'],
              }
          }, test_failed_builds=True, is_bazel=True,
          expected_is_green_for_local=False),
      api.post_process(post_process.DropExpectation),
  )
