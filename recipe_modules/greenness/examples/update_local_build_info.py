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

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='eve', status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='eve-not-relevant', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'not relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='eve-cpp20-variant-excluded', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
  ]

  api.greenness.update_local_build_info(builds)

  api.assertions.assertEqual(
      api.greenness.local_greenness_dict['eve-postsubmit'].build_score, 100)
  api.assertions.assertNotIn('eve-not-relevant',
                             api.greenness.local_greenness_dict.keys())
  api.assertions.assertNotIn('eve-cpp20-variant-excluded',
                             api.greenness.local_greenness_dict.keys())


def GenTests(api):
  yield api.test('basic')
