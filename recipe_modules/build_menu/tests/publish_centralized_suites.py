# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for build_menu.publish_centralized_suites"""

from recipe_engine import post_process

DEPS = [
    'cros_build_api',
    'build_menu',
    'recipe_engine/buildbucket',
]


def RunSteps(api):
  api.build_menu.publish_centralized_suites()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.MustRun,
                     'publish centralized suites.run suite_publisher'),
      api.post_check(
          post_process.StepCommandContains,
          'publish centralized suites.run suite_publisher',
          ['cros-test-analytics'],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fetch-centralized-suites-endpoint-does-not-exist',
      api.cros_build_api.remove_endpoints(
          ['ArtifactsService/FetchCentralizedSuites']),
      api.post_check(post_process.DoesNotRun,
                     'publish centralized suites.run suite_publisher'),
      api.post_check(post_process.StepFailure, 'publish centralized suites'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'staging',
      api.buildbucket.generic_build(bucket='staging',
                                    builder='amd64-generic-cq'),
      api.post_check(post_process.MustRun,
                     'publish centralized suites.run suite_publisher'),
      api.post_check(
          post_process.StepCommandContains,
          'publish centralized suites.run suite_publisher',
          ['cros-test-analytics-staging'],
      ),
      api.post_process(post_process.DropExpectation),
  )
