# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test updating build info for local greenness."""

DEPS = [
    'recipe_engine/assertions',
    'cros_tags',
    'greenness',
    'test_util',
]



def RunSteps(api):
  current_snapshot_builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='eve', status='FAILURE', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='grunt', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'not relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='eve-cpp20-variant-excluded', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
  ]

  api.greenness.populate_local_build_info(current_snapshot_builds)

  # Relevant build target that failed has a score of 0.
  api.assertions.assertEqual(
      api.greenness.local_greenness_dict['eve-postsubmit'].build_score, 0)
  # Irrelevant build target has a score of -1 when the local greenness dict is
  # initially populated.
  api.assertions.assertEqual(
      api.greenness.local_greenness_dict['grunt-postsubmit'].build_score, -1)
  # Excluded variants are not in the local greenness dict.
  api.assertions.assertNotIn('eve-cpp20-variant-excluded',
                             api.greenness.local_greenness_dict.keys())

  previous_snapshot_builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='eve', status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='grunt', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='eve-cpp20-variant-excluded', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
  ]

  api.greenness.update_irrelevant_builds_scores(
      previous_snapshot_builds, api.greenness.local_greenness_dict)

  # Relevant build target is not updated by the previous snapshot build result.
  api.assertions.assertEqual(
      api.greenness.local_greenness_dict['eve-postsubmit'].build_score, 0)
  # Irrelevant build target is updated by the previous snapshot build result.
  api.assertions.assertEqual(
      api.greenness.local_greenness_dict['grunt-postsubmit'].build_score, 100)
  # Excluded variants are not in the local greenness dict.
  api.assertions.assertNotIn('eve-cpp20-variant-excluded',
                             api.greenness.local_greenness_dict.keys())


def GenTests(api):
  yield api.test('basic')
