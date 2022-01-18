# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'greenness',
    'test_util',
]


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='eve-kernelnext', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          build_target_name='eve-kernelnext-not-relevant', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'not relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          builder='eve-asan-postsubmit', build_target_name='eve',
          status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
  ]
  api.greenness.update_build_info(builds)
  api.assertions.assertEqual(
      api.greenness.greenness_dict['eve-kernelnext'].score, 100)
  api.assertions.assertEqual(api.greenness.get_greenness('eve'), None)
  api.greenness.print_step()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}))
