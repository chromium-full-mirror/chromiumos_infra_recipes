# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_relevance',
    'git_footers',
]

from recipe_engine import post_process


def RunSteps(api):
  api.assertions.assertEqual(api.build_menu.is_cq_build_relevant(),
                             api.properties.get('expected_relevance'))


def GenTests(api):

  yield api.test('relevant-packages', api.properties(expected_relevance=True))

  yield api.test(
      'toolchain-cls-applied',
      api.cros_relevance.toolchain_cls_applied(True),
      api.properties(expected_relevance=True),
      api.post_check(post_process.DoesNotRun, 'get package dependencies'),
  )

  yield api.test(
      'force-relevant-property',
      api.properties(**{'$chromeos/build_menu': {
          'force_relevant_build': True
      }}),
      api.properties(expected_relevance=True),
      api.post_check(post_process.DoesNotRun, 'get package dependencies'),
  )

  yield api.test(
      'no-relevant-packages',
      api.cros_build_api.set_api_return('get package dependencies',
                                        endpoint='DependencyService/List',
                                        data='{"package_deps": []}'),
      api.properties(expected_relevance=False),
  )
