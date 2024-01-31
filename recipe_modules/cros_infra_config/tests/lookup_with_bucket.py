# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'depot_tools/gitiles',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  config = api.cros_infra_config.configure_builder(
      lookup_config_with_bucket=True)
  api.assertions.assertEqual(config.id.name, 'generic-staging-builder')
  api.assertions.assertEqual(config.id.bucket, 'staging')

  config = api.cros_infra_config.configure_builder(
      lookup_config_with_bucket=False)
  api.assertions.assertEqual(config.id.name, 'generic-staging-builder')
  api.assertions.assertEqual(config.id.bucket, 'try-dev')


def GenTests(api):

  yield api.test(
      'basic',
      api.test_util.test_child_build('eve',
                                     builder_name='generic-staging-builder',
                                     bucket='staging').build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-shadow-bucket',
      api.test_util.test_child_build('eve',
                                     builder_name='generic-staging-builder',
                                     bucket='staging.shadow').build,
      api.properties(**{'$recipe_engine/led': {
          'shadowed_bucket': 'staging',
      }}),
      api.post_process(post_process.DropExpectation),
  )
