# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.snapshot_orch_menu.tests.collect_and_check_build_results import CollectAndCheckBuildResultsProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'snapshot_orch_menu',
    'test_util',
]

PROPERTIES = CollectAndCheckBuildResultsProperties


def RunSteps(api, properties):
  # Start off with some data in snapshot_orch_menu.builds_status since the function being
  # tested gets called multiple times in the same orchestrator.
  irrelevant_build = api.test_util.test_api.test_child_build(
      build_target_name='ttarget-0', builder_name='ttarget-0-env',
      status='SUCCESS', critical='YES',
      tags=api.cros_tags.tags(**{'relevance': 'not relevant'}),
      output_properties={
          'relevant_build': False
      }).message
  api.snapshot_orch_menu.builds_status.update(completed=[irrelevant_build])

  # Function call.
  api.snapshot_orch_menu._collect_and_check_build_results(
      properties.input_builds)

  # Assertions.
  api.assertions.assertCountEqual(
      list(properties.input_builds) + [irrelevant_build],
      api.snapshot_orch_menu.builds_status.completed_builds,
  )


def GenTests(api):
  successful = api.test_util.test_child_build(build_target_name='grunt',
                                              status='SUCCESS',
                                              critical='YES').message
  failure = api.test_util.test_child_build(build_target_name='amd64-generic',
                                           status='FAILURE',
                                           critical='YES').message

  irrelevant = api.test_util.test_child_build(
      build_target_name='atlas', status='SUCCESS', critical='YES',
      tags=api.cros_tags.tags(**{'relevance': 'not relevant'})).message

  yield api.test(
      'postsubmit', api.buildbucket.ci_build(builder='postsubmit-orchestrator'),
      api.properties(
          CollectAndCheckBuildResultsProperties(
              input_builds=[
                  successful,
                  failure,
                  irrelevant,
              ],
          )))

  yield api.test(
      'snapshot-mixed-relevancy',
      api.buildbucket.ci_build(builder='snapshot-orchestrator'),
      api.post_check(post_process.PropertiesDoNotContain,
                     'sheriff_ignore_build'),
      api.post_check(post_process.PropertiesDoNotContain,
                     'all_critical_builds_irrelevant'),
      api.properties(
          CollectAndCheckBuildResultsProperties(
              input_builds=[
                  successful,
                  failure,
                  irrelevant,
              ],
          )))

  yield api.test(
      'snapshot-all-irrelevant',
      api.buildbucket.ci_build(builder='snapshot-orchestrator'),
      api.post_check(post_process.PropertyEquals,
                     'all_critical_builds_irrelevant', True),
      api.post_check(post_process.PropertyEquals, 'sheriff_ignore_build', True),
      api.properties(
          CollectAndCheckBuildResultsProperties(input_builds=[
              irrelevant,
          ])))

  # Although the build is critical, the builder config is non-critical, so the
  # result will no longer be fatal.
  newly_non_critical_failure = api.test_util.test_child_build(
      build_target_name='coral', builder_name='coral-cq', status='FAILURE',
      critical='YES').message

  yield api.test(
      'non-crit-update', api.buildbucket.ci_build(builder='cq-orchestrator'),
      api.properties(
          CollectAndCheckBuildResultsProperties(
              input_builds=[
                  failure,
                  newly_non_critical_failure,
              ],
          )))
