# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_relevance',
    'git_footers',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.workspace_util.apply_changes()
  api.assertions.assertEqual(api.build_menu.is_cq_build_relevant(),
                             api.properties.get('expected_relevance'))


def GenTests(api):

  yield api.test('relevant-packages',
                 api.buildbucket.try_build(builder='amd64-generic-cq'),
                 api.properties(expected_relevance=True))

  yield api.test(
      'toolchain-cls-applied',
      api.buildbucket.try_build(builder='amd64-generic-cq'),
      api.cros_relevance.toolchain_cls_applied(True),
      api.properties(expected_relevance=True),
      api.post_check(post_process.DoesNotRun, 'get package dependencies'),
  )

  yield api.test(
      'force-relevant-property',
      api.buildbucket.try_build(builder='amd64-generic-cq'),
      api.properties(**{'$chromeos/build_menu': {
          'force_relevant_build': True
      }}),
      api.properties(expected_relevance=True),
      api.post_check(post_process.DoesNotRun, 'get package dependencies'),
  )

  yield api.test(
      'no-relevant-packages',
      api.buildbucket.try_build(builder='amd64-generic-cq'),
      api.cros_build_api.set_api_return('get package dependencies',
                                        endpoint='DependencyService/List',
                                        data='{"package_deps": []}'),
      api.properties(expected_relevance=False),
  )
