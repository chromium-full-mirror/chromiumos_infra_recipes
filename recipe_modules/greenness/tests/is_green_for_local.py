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
          builder='eve-kernelnext-postsubmit',
          build_target_name='eve-kernelnext', critical='YES', status='FAILURE',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          builder='eve-postsubmit', build_target_name='eve', critical='YES',
          status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message
  ]
  failed_builds = [
      api.test_util.test_api.test_child_build(
          builder='amd64-generic-postsubmit', build_target_name='amd64-generic',
          critical='YES', status='FAILURE', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message
  ]
  if api.properties['failed_builds']:
    api.greenness.update_build_info(builds + failed_builds)
  else:
    api.greenness.update_build_info(builds)

  api.assertions.assertEqual(api.greenness.is_green_for_local(),
                             api.properties['expected_is_green_for_local'])


def GenTests(api):

  yield api.test(
      'is-green-for-local',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}, failed_builds=False, expected_is_green_for_local=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'is-not-green-for-local',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}, failed_builds=True, expected_is_green_for_local=False),
      api.post_process(post_process.DropExpectation),
  )
