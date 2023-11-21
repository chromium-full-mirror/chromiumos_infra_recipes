# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the `publish snapshot metadata` functionality of the module."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket', 'recipe_engine/properties',
    'recipe_engine/step', 'binhost_lookup_service'
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  with api.step.nest('test publish snapshot metadata'):
    api.binhost_lookup_service.publish_snapshot_metadata(
        snapshot_sha='1', snapshot_num=2, external=True, buildbucket_id=3,
        raise_on_failure=api.properties['raise_on_failure'])
    api.binhost_lookup_service.publish_snapshot_metadata(
        snapshot_sha='4', snapshot_num=5, external=False, buildbucket_id=6,
        raise_on_failure=api.properties['raise_on_failure'])


def GenTests(api: RecipeTestApi):

  # Publish snapshot metadata in a staging builder using the
  # binhost_lookup_service module.
  yield api.test(
      'publish-snapshot-metadata-staging',
      api.properties(raise_on_failure=False,
                     **api.binhost_lookup_service.input_properties),
      api.buildbucket.generic_build(
          builder='staging-'
      ),  # The `cros_infra_config` module checks for the builder name to determine if its a staging builder.
      api.post_check(
          post_process.StepSuccess, 'test publish snapshot metadata.'
          'publish external snapshot metadata.publish message.publish-message'),
      api.post_check(
          post_process.LogContains, 'test publish snapshot metadata.'
          'publish external snapshot metadata.publish message', 'request',
          ['staging-test_topic_id_update_snapshot_data']),
      api.post_check(
          post_process.StepSuccess, 'test publish snapshot metadata.'
          'publish internal snapshot metadata.publish message.publish-message'),
      api.post_check(post_process.StepSuccess,
                     'test publish snapshot metadata'),
      api.post_process(post_process.DropExpectation))

  # Publish snapshot metadata in a prod builder using the
  # binhost_lookup_service module.
  yield api.test(
      'publish-snapshot-metadata-prod',
      api.properties(raise_on_failure=False,
                     **api.binhost_lookup_service.input_properties),
      api.buildbucket.generic_build(builder=''),
      api.post_check(
          post_process.StepSuccess, 'test publish snapshot metadata.'
          'publish external snapshot metadata.publish message.publish-message'),
      api.post_check(
          post_process.LogContains, 'test publish snapshot metadata.'
          'publish external snapshot metadata.publish message', 'request',
          ['prod-test_topic_id_update_snapshot_data']),
      api.post_check(
          post_process.StepSuccess, 'test publish snapshot metadata.'
          'publish internal snapshot metadata.publish message.publish-message'),
      api.post_check(post_process.StepSuccess,
                     'test publish snapshot metadata'),
      api.post_process(post_process.DropExpectation))

  # When `pubsub_project_id` is not passed, the build still succeeds because
  # `publish_snapshot_metadata` has `raise_on_failure=False` by default. The
  # exception is caught and logged.
  yield api.test(
      'missing-required-property-project_id',
      api.properties(
          raise_on_failure=False, **{
              '$chromeos/binhost_lookup_service': {
                  'pubsub_topic_id_update_snapshot_data':
                      'test_topic_id_update_snapshot_data',
                  'pubsub_topic_id_update_binhost_data':
                      'test_topic_id_update_binhost_data'
              }
          }),
      api.post_check(post_process.StepException,
                     'test publish snapshot metadata'),
      api.post_check(
          post_process.LogContains,
          'test publish snapshot metadata.publish external snapshot metadata',
          'caught exception', ['Must set pubsub_project_id']),
      api.post_process(post_process.DropExpectation))

  # When `pubsub_topic_id_update_snapshot_data` is not passed, the build still
  # succeeds because `publish_snapshot_metadata` has `raise_on_failure=False`
  # by default. The exception is caught and logged.
  yield api.test(
      'missing-required-property-topic_snapshot_data',
      api.properties(
          raise_on_failure=False, **{
              '$chromeos/binhost_lookup_service': {
                  'pubsub_project_id':
                      'chromeos-prebuilts',
                  'pubsub_topic_id_update_binhost_data':
                      'test_topic_id_update_binhost_data'
              }
          }),
      api.post_check(post_process.StepException,
                     'test publish snapshot metadata'),
      api.post_check(
          post_process.LogContains,
          'test publish snapshot metadata.publish external snapshot metadata',
          'caught exception',
          ['Must set pubsub_topic_id_update_snapshot_data']),
      api.post_process(post_process.DropExpectation))

  # Properties not passed but build still succeeds when
  # `raise_on_failure=False`.
  yield api.test('passes-non-critical-publish',
                 api.properties(raise_on_failure=False),
                 api.post_process(post_process.DropExpectation))

  # Properties not passed so build fails when `raise_on_failure=True`.
  yield api.test('fails-critical-publish',
                 api.properties(raise_on_failure=True),
                 api.post_process(post_process.DropExpectation),
                 status='INFRA_FAILURE')
