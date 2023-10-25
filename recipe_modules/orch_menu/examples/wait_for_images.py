# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the plan_and_wait_for_images function."""

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.builds_service import (
    BatchResponse)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'orch_menu',
]


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    # There should be no running builds after setup.
    api.assertions.assertEqual(
        len(api.orch_menu.builds_status.running_builds), 0)

    testable_builds = api.orch_menu.plan_and_wait_for_images()
    expected_testable_builders = [
        'arm-generic-cq',
        'arm64-generic-cq',
        'atlas-cq',
        'amd64-generic-cq',
    ]
    api.assertions.assertCountEqual(
        [b.builder.builder for b in testable_builds],
        expected_testable_builders)

    # plan_and_wait_for_images should add all builds to
    # build_status.running builds.
    all_expected_builders = [
        'amd64-generic-cq',
        'arm-generic-cq',
        'arm64-generic-cq',
        'atlas-cq',
        'cave-cq',
        'coral-cq',
        'eve-cq',
    ]
    api.assertions.assertCountEqual(
        [b.builder.builder for b in api.orch_menu.builds_status.running_builds],
        all_expected_builders)

    # All builders should still be in "running" state after plan_and_run_tests.
    api.orch_menu.plan_and_run_tests(testable_builds=testable_builds)
    api.assertions.assertCountEqual(
        [b.builder.builder for b in api.orch_menu.builds_status.running_builds],
        all_expected_builders)
    api.assertions.assertEqual(
        len(api.orch_menu.builds_status.completed_builds), 0)

    # All builders should be in "completed" state after the final build collect.
    api.orch_menu.create_recipe_result()
    api.assertions.assertCountEqual([
        b.builder.builder for b in api.orch_menu.builds_status.completed_builds
    ], all_expected_builders)
    api.assertions.assertEqual(
        len(api.orch_menu.builds_status.running_builds), 0)


def GenTests(api):
  # arm-generic-cq is originally in STARTED status, with a published image.
  build_with_published_image = api.buildbucket.ci_build_message(
      build_id=8922054662172514001,
      builder='arm-generic-cq',
      status='STARTED',
  )

  # amd64-generic-cq transitions to STARTED status, with a published image.
  other_build_with_published_image = api.buildbucket.ci_build_message(
      build_id=8922054662172514000,
      builder='amd64-generic-cq',
      status='STARTED',
  )
  build_with_published_image.output.properties[
      'image_artifacts_uploaded'] = True
  other_build_with_published_image.output.properties[
      'image_artifacts_uploaded'] = True

  # arm64-generic-cq is originally in SUCCESS status.
  successful_build = api.buildbucket.ci_build_message(
      build_id=8922054662172514002,
      builder='arm64-generic-cq',
      status='SUCCESS',
  )

  # atlas-cq is originally in FAILURE status.
  failed_build = api.buildbucket.ci_build_message(
      build_id=8922054662172514003,
      builder='atlas-cq',
      status='FAILURE',
  )

  # The rest of these builds have COLLECT_AFTER_HW_TEST set.
  cave = api.buildbucket.ci_build_message(
      build_id=8922054662172514004,
      builder='cave-cq',
      status='SUCCESS',
  )
  coral = api.buildbucket.ci_build_message(
      build_id=8922054662172514005,
      builder='coral-cq',
      status='SUCCESS',
  )
  eve = api.buildbucket.ci_build_message(
      build_id=8922054662172514006,
      builder='eve-cq',
      status='SUCCESS',
  )

  builds = [
      build_with_published_image,
      other_build_with_published_image,
      successful_build,
      failed_build,
      cave,
      coral,
      eve,
  ]

  completed_builds = []
  for b in builds:
    new_b = Build()
    new_b.CopyFrom(b)
    if new_b.status == common_pb2.STARTED:
      new_b.status = common_pb2.SUCCESS
    completed_builds.append(new_b)

  def schedule_output(api):
    test_data = None
    for b in builds:
      build_test_data = api.buildbucket.simulated_schedule_output(
          BatchResponse(responses=[{
              'schedule_build': b
          }]), 'run builds.schedule new builds.%s' % b.builder.builder)
      if not test_data:
        test_data = build_test_data
      else:
        test_data += build_test_data
    return test_data

  yield api.orch_menu.test(
      'basic',
      schedule_output(api),
      api.buildbucket.simulated_collect_output(completed_builds,
                                               'final build collect.collect'),
      # Expect to schedule 7 child builds. 4 should have COLLECT behavior, so
      # are included in the call build_poller.
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.amd64-generic-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.arm-generic-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.arm64-generic-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.atlas-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.cave-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.coral-cq'),
      api.post_check(post_process.MustRun,
                     'run builds.schedule new builds.eve-cq'),
      api.orch_menu.build_poller_step_data(
          builds=[
              build_with_published_image, successful_build, failed_build,
              other_build_with_published_image
          ], parent_step_name='run builds'),
      api.post_check(post_process.StepCommandContains, 'run builds.collect', [
          '[START_DIR]/cipd/build_poller/build_poller', 'collect', '-loglevel',
          'debug', '-outputprop', 'image_artifacts_uploaded', '-interval',
          '60s', '-json', '-', '8922054662172514000', '8922054662172514001',
          '8922054662172514002', '8922054662172514003'
      ]),
      # The final build collect should collect all 7 builds.
      api.post_check(post_process.StepCommandRE,
                     'final build collect.collect.wait', [
                         'bb', 'collect', '-host', '.*', '-interval', '.*',
                         '8922054662172514000', '8922054662172514001',
                         '8922054662172514002', '8922054662172514003',
                         '8922054662172514004', '8922054662172514005',
                         '8922054662172514006'
                     ]),
      api.post_check(post_process.MustRun,
                     'final build collect.check build results'),
      cq=True,
  )

  yield api.orch_menu.test(
      'updates-refs',
      api.expect_exception('ValueError'),
      api.post_check(
          post_process.ResultReasonRE,
          'currently plan_and_wait_for_images cannot be called when update_manifest_refs is set.'
      ),
      api.post_process(post_process.DropExpectation),
      with_manifest_refs=True,
      status='INFRA_FAILURE',
  )

  yield api.orch_menu.test(
      'times-out',
      schedule_output(api),
      api.buildbucket.simulated_collect_output(builds,
                                               'final build collect.collect'),
      # If the build_poller command times out, a get_multi should run after.
      api.step_data('run builds.collect', times_out_after=60 * 60 * 40),
      api.buildbucket.simulated_get_multi([
          build_with_published_image, successful_build, failed_build,
          other_build_with_published_image
      ], step_name='run builds.collect after timeout'),
      # The final build collect should collect all 7 builds.
      api.post_check(post_process.StepCommandRE,
                     'final build collect.collect.wait', [
                         'bb', 'collect', '-host', '.*', '-interval', '.*',
                         '8922054662172514000', '8922054662172514001',
                         '8922054662172514002', '8922054662172514003',
                         '8922054662172514004', '8922054662172514005',
                         '8922054662172514006'
                     ]),
      api.post_check(post_process.MustRun,
                     'final build collect.check build results'),
      api.post_process(post_process.DropExpectation),
      cq=True,
  )

  yield api.orch_menu.test(
      'build-poller-fails',
      api.step_data('run builds.collect', retcode=1),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
