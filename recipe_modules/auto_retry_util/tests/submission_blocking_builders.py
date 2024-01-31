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
    'auto_retry_util',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  # pylint: disable=protected-access
  actual = api.auto_retry_util._submission_blocking_builders(
      api.buildbucket.build)
  expected = api.properties['expected_submission_blocking_builders']
  api.assertions.assertCountEqual(actual, expected)


def GenTests(api):
  _default_child_builders = []
  for config in api.cros_infra_config.builder_configs_test_data.builder_configs:
    if config.id.name == 'cq-orchestrator':
      _default_child_builders = [
          c.name for c in config.orchestrator.child_specs
      ]

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      api.properties(
          expected_submission_blocking_builders=sorted(
              _default_child_builders)),
  )

  build = api.test_util.test_orchestrator(
      cq=True, output_properties={
          'found_force_relevant_targets': ['random-cq']
      }).build
  expected = _default_child_builders + ['random-cq']
  yield api.test(
      'with-forced-relevant',
      build,
      api.properties(expected_submission_blocking_builders=expected),
      api.post_process(post_process.DropExpectation),
  )
