# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
]



def RunSteps(api):

  _ = api.auto_retry_util.experimental_retries
  enabled = api.auto_retry_util.is_experimental_feature_enabled(
      api.properties['feature_name'], api.buildbucket.build)
  api.assertions.assertEqual(enabled, api.properties['expected_enabled'])


def GenTests(api):
  auto_retry_props = AutoRetryUtilProperties(experimental_features=[
      ExperimentalFeature(name='do-something'),
      ExperimentalFeature(name='do-something-else',
                          experiment_flag='do-something-else-experiment')
  ])

  yield api.test(
      'globally-enabled-feature',
      api.properties(**{'$chromeos/auto_retry_util': auto_retry_props}),
      api.properties(feature_name='do-something', expected_enabled=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'experiment-gated-feature',
      api.buildbucket.try_build(experiments=['do-something-else-experiment']),
      api.properties(**{'$chromeos/auto_retry_util': auto_retry_props}),
      api.properties(feature_name='do-something-else', expected_enabled=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-run-does-not-have-required-experiment',
      api.buildbucket.try_build(experiments=['do-something-else-experiment']),
      api.properties(**{'$chromeos/auto_retry_util': auto_retry_props}),
      api.properties(feature_name='undefined-something',
                     expected_enabled=False),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'undefined-feature',
      api.buildbucket.try_build(experiments=['do-something-experiment']),
      api.properties(**{'$chromeos/auto_retry_util': auto_retry_props}),
      api.properties(feature_name='undefined-something',
                     expected_enabled=False),
      api.post_process(post_process.DropExpectation),
  )
