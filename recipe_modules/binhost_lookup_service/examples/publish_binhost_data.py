# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the `publish binhost metadata` functionality of the module."""

from PB.chromiumos import common as common_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties', 'recipe_engine/buildbucket',
    'recipe_engine/step', 'binhost_lookup_service'
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  with api.step.nest('test publish binhost metadata'):
    api.binhost_lookup_service.publish_binhost_metadata(
        build_target=common_pb2.BuildTarget(name='test_target'),
        profile=common_pb2.Profile(name='test_profile'), snapshot_sha='1',
        gs_uri='gs://test', gs_bucket_name='test_bucket', buildbucket_id=2,
        complete=True, private=True,
        raise_on_failure=api.properties['raise_on_failure'])


def GenTests(api: RecipeTestApi):

  # Publish binhost metadata in a staging builder using the
  # binhost_lookup_service module.
  yield api.test(
      'publish-binhost-metadata-staging',
      api.buildbucket.generic_build(bucket='staging'),
      api.properties(raise_on_failure=False,
                     **api.binhost_lookup_service.input_properties),
      api.post_check(
          post_process.LogContains,
          'test publish binhost metadata.publish binhost metadata.'
          'publish message', 'request', ['staging-']),
      api.post_check(
          post_process.LogContains,
          'test publish binhost metadata.publish binhost metadata.publish message',
          'request', ['staging-']),
      api.post_check(
          post_process.StepSuccess, 'test publish binhost metadata.'
          'publish binhost metadata.publish message.publish-message'),
      api.post_check(post_process.StepSuccess, 'test publish binhost metadata'),
      api.post_process(post_process.DropExpectation))

  # Publish binhost metadata in a prod builder using the
  # binhost_lookup_service module.
  yield api.test(
      'publish-binhost-metadata-prod',
      api.properties(raise_on_failure=False,
                     **api.binhost_lookup_service.input_properties),
      api.post_check(
          post_process.LogContains,
          'test publish binhost metadata.publish binhost metadata.'
          'publish message', 'request', ['prod-']),
      api.post_check(
          post_process.LogContains,
          'test publish binhost metadata.publish binhost metadata.publish message',
          'request', ['prod-']),
      api.post_check(
          post_process.StepSuccess, 'test publish binhost metadata.'
          'publish binhost metadata.publish message.publish-message'),
      api.post_check(post_process.StepSuccess, 'test publish binhost metadata'),
      api.post_process(post_process.DropExpectation))

  # When `pubsub_project_id` is not passed, the build still succeeds because
  # `publish_binhost_metadata` has `raise_on_failure=False` by default. The
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
                     'test publish binhost metadata'),
      api.post_check(post_process.LogContains,
                     'test publish binhost metadata.publish binhost metadata',
                     'caught exception', ['Must set pubsub_project_id']),
      api.post_process(post_process.DropExpectation))

  # When `pubsub_topic_id_update_binhost_data` is not passed, the build still
  # succeeds because `publish_binhost_metadata` has `raise_on_failure=False`
  # by default. The exception is caught and logged.
  yield api.test(
      'missing-required-property-topic_binhost_data',
      api.properties(
          raise_on_failure=False, **{
              '$chromeos/binhost_lookup_service': {
                  'pubsub_project_id':
                      'chromeos-prebuilts',
                  'pubsub_topic_id_update_snapshot_data':
                      'test_topic_id_update_snapshot_data'
              }
          }),
      api.post_check(post_process.StepException,
                     'test publish binhost metadata'),
      api.post_check(post_process.LogContains,
                     'test publish binhost metadata.publish binhost metadata',
                     'caught exception',
                     ['Must set pubsub_topic_id_update_binhost_data']),
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
