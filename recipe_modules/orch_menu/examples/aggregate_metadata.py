# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import functools
import json

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.orch_menu.examples.aggregate_metadata import AggregateProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'orch_menu',
]


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
                '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
        }

      # Setup builder info
      build.builder.builder = 'test-target-{}'.format(ii)

      # Setup the input properties
      build.input.properties['$chromeos/build_menu'] = build_menu_props

      # Add the build_target config to the builder.
      if not build.id in properties.skip_build_target:
        build.input.properties['build_target'] = {
            'name': 'test-target-{}'.format(ii)
        }

      # Mock the output properties.
      if not build.id in properties.skip_artifacts:
        build.output.properties['artifacts'] = {
            'gs_bucket': 'gs://test-bucket',
            'gs_path': 'test-builder-{}/R97-14304.0.0-55874'.format(ii),
        }

      # If we're mocking a failed child build, then update the build status.
      if build.id in properties.failed_builds:
        build.status = common_pb2.Status.FAILURE

    api.orch_menu.aggregate_metadata(builds_status.completed_builds)


def GenTests(api):

  def set_test_properties(**kwargs):
    return api.properties(AggregateProperties(**kwargs))

  def mock_metadata(skip=None):
    skip = skip or []

    data = []
    for ii in range(2):
      if ii in skip:
        continue

      target = 'test-target-{}'.format(ii)
      step_data = api.step_data(
          'aggregating metadata'
          '.container metadata'
          '.processing {target}'
          '.gsutil reading payload for {target}'.format(target=target),
          stdout=api.raw_io.output(
              json.dumps(
                  {
                      'containers': {
                          target: {
                              'images': {
                                  'some-service': {
                                      'digest': '123abc',
                                  },
                              },
                          }
                      }
                  }, separators=(',', ': '), indent=2, sort_keys=True),
          ))
      data.append(step_data)

    result = data[0]
    for dd in data[1:]:
      result += dd
    return result

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
      mock_metadata(),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-0.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*writing metadata.*'),
      step_passed('aggregating metadata'),
      step_passed('aggregating metadata.container metadata'),
  )

  yield api.orch_menu.test(
      'skip-child',
      set_test_properties(skip_builds=[CHILD_BUILDS[1]]),
      mock_metadata(skip=[0]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          StepLogEquals,
          'aggregating metadata.container metadata',
          'skipped build info',
          'test-target-0 - containers not configured',
      ),
  )

  yield api.orch_menu.test(
      'skip-build-target',
      set_test_properties(skip_build_target=[CHILD_BUILDS[1]]),
      mock_metadata(skip=[0]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          post_process.StepSummaryEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'no build-target set, skipping',
      ),
  )

  yield api.orch_menu.test(
      'skip-artifacts',
      set_test_properties(skip_artifacts=[CHILD_BUILDS[1]]),
      mock_metadata(skip=[0]),
      require_step('aggregating metadata.*'),
      require_step('.*container metadata.*'),
      require_step('.*reading payload for test-target-1.*'),
      require_step('.*writing metadata.*'),
      api.post_check(
          post_process.StepSummaryEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'no artifacts path, skipping',
      ),
  )

  yield api.orch_menu.test(
      'failed-reading',
      mock_metadata(),
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

  yield api.orch_menu.test(
      'failed-decoding',
      step_failed('aggregating metadata'),
      step_failed('aggregating metadata.container metadata'),
      api.post_process(
          post_process.StepTextEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'failed to parse'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.orch_menu.test(
      'failed-reading-but-forgiven',
      set_test_properties(failed_builds=[CHILD_BUILDS[1]]),
      mock_metadata(),
      api.step_data(
          'aggregating metadata'
          '.container metadata'
          '.processing test-target-0'
          '.gsutil reading payload for test-target-0',
          retcode=1,
      ),
      step_passed('aggregating metadata'),
      step_passed('aggregating metadata.container metadata'),
      step_passed('aggregating metadata'
                  '.container metadata'
                  '.processing test-target-0'),
      api.post_check(
          post_process.StepSummaryEquals,
          'aggregating metadata.container metadata.processing test-target-0',
          'no metadata but build failed, ignoring.'),
  )
