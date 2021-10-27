# -*- coding: utf-8 -*-

# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'orch_menu',
]

import functools
import json

# Recipe engine imports
from recipe_engine import post_process

# Local imports
from PB.recipe_modules.chromeos.orch_menu.examples.aggregate_metadata import AggregateProperties

PROPERTIES = AggregateProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  with api.orch_menu.setup_orchestrator():
    builds_status = api.orch_menu.plan_and_run_children()

    # Add properties to the child builds
    for ii, build in enumerate(builds_status.completed_builds):
      # We check whether children were told to build containers, so mock that
      build_menu_props = {}
      if not build.id in properties.skip_builds:
        build_menu_props = {
            'container_version_format':
                '{staging?}{build-target}-postsubmit.{cros-version}-{bbid}',
        }

      # Setup builder info
      build.builder.builder = 'test-target-{}'.format(ii)

      # Setup the input properties
      build.input.properties['$chromeos/build_menu'] = build_menu_props

      if not build.id in properties.skip_build_target:
        build.input.properties['build_target'] = {
            'name': 'test-target-{}'.format(ii)
        }

      # Mock the output properties
      if not build.id in properties.skip_artifacts:
        build.output.properties['artifacts'] = {
            'gs_bucket': 'gs://test-bucket',
            'gs_path': 'test-builder-{}/R97-14304.0.0-55874'.format(ii),
        }

    api.orch_menu.aggregate_metadata(builds_status.completed_builds)


def GenTests(api):

  def set_test_properties(**kwargs):
    return api.properties(AggregateProperties(**kwargs))

  def mock_metadata(step, data):
    return api.step_data(
        step,
        stdout=api.raw_io.output(data),
    )

  # flattening stage tests
  def StepLogEquals(check, step_odict, step, logkey, expected):
    """Check that the step's log under logkey equals given value.

    Args:
      step (str) - The step to check the step_text of
      logkey (str) - Key to use for the log name
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + \
          api.post_process(StepLogEquals, 'step-name', 'log-key', 'expected-text')
    """
    check(step_odict[step].logs[logkey] == expected)

  def StepSummaryEquals(check, step_odict, step, expected):
    """Check that the step's step_summary_text equals given value.

    Args:
      step (str) - The step to check the step_text of
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_summary_text == expected)

  # Convenience bindings for common test assertions
  require_step = functools.partial(api.post_check, post_process.MustRunRE)
  step_failed = functools.partial(api.post_check, post_process.StepFailure)
  step_passed = functools.partial(api.post_check, post_process.StepSuccess)

  # BuildBucket IDs used by children
  CHILD_BUILDS = [
      8922054662172514000,
      8922054662172514001,
      8922054662172514002,
  ]

  yield api.orch_menu.test(
      'basic',
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-0.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*reading payload for test-target-2.*'),
      require_step('.*writing metadata.*'),
      mock_metadata(
          'aggregating metadata'
          '.container metadata'
          '.processing test-target-0'
          '.gsutil reading payload for test-target-0',
          json.dumps({
              'containers': {
                  'test-target-0': {
                      'images': {
                          'some-service': {
                              'digest': '123abc',
                          },
                      },
                  }
              }
          })),
      step_passed('aggregating metadata'),
      step_passed('aggregating metadata.container metadata'),
  )

  yield api.orch_menu.test(
      'skip-child',
      set_test_properties(skip_builds=[CHILD_BUILDS[0]]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*reading payload for test-target-2.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          StepLogEquals,
          'aggregating metadata.container metadata',
          'skipped children',
          'test-target-0',
      ),
  )

  yield api.orch_menu.test(
      'skip-build-target',
      set_test_properties(skip_build_target=[CHILD_BUILDS[0]]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*reading payload for test-target-2.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          StepSummaryEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'no build-target set, skipping',
      ),
  )

  yield api.orch_menu.test(
      'skip-artifacts',
      set_test_properties(skip_artifacts=[CHILD_BUILDS[0]]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*reading payload for test-target-2.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          StepSummaryEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'no artifacts path, skipping',
      ),
  )

  yield api.orch_menu.test(
      'failed-reading',
      api.step_data(
          'aggregating metadata'
          '.container metadata'
          '.processing test-target-1'
          '.gsutil reading payload for test-target-1',
          retcode=1,
      ),
      step_failed('aggregating metadata'),
      step_failed('aggregating metadata.container metadata'),
  )
