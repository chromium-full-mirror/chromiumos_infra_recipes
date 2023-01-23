# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'orch_menu',
]


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    # There should be no running builds after setup.
    api.assertions.assertEqual(
        len(api.orch_menu.builds_status.running_builds), 0)
    testable_builds = api.orch_menu.plan_and_wait_for_images()
    api.assertions.assertEqual(
        [b.builder.builder for b in testable_builds],
        ['arm-generic-cq', 'arm64-generic-cq', 'atlas-cq', 'amd64-generic-cq'])

    # plan_and_wait_for_images should add all builds to
    # build_status.running builds.
    api.assertions.assertEqual(
        [b.builder.builder for b in api.orch_menu.builds_status.running_builds],
        [
            'amd64-generic-cq', 'arm-generic-cq', 'arm64-generic-cq',
            'atlas-cq', 'cave-cq', 'coral-cq', 'eve-cq'
        ])

    builds_status = api.orch_menu.plan_and_run_tests(
        testable_builds=testable_builds)

    # plan_and_run_tests should collect all the running builds.
    api.assertions.assertEqual(len(builds_status.running_builds), 0)


def GenTests(api):
  # amd64-generic-cq is originally in STARTED status, with no published image.
  running_build = api.buildbucket.ci_build_message(
      build_id=8922054662172514000,
      builder='amd64-generic-cq',
      status='STARTED',
  )
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

  yield api.orch_menu.test(
      'basic',
      # Expect to schedule 7 child builds. 4 should have COLLECT behavior, so
      # are included in the calls to get_multi.
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
      # First call to get_multi has a build that is still running, and hasn't published an image.
      api.buildbucket.simulated_get_multi([
          running_build,
          build_with_published_image,
          successful_build,
          failed_build,
      ], step_name='run builds.collect.buildbucket.get_multi'),
      api.post_process(post_process.LogEquals,
                       'run builds.collect.buildbucket.get_multi',
                       'running builds', '8922054662172514000'),
      # Second call all builds have completed or published an image.
      api.buildbucket.simulated_get_multi([
          other_build_with_published_image,
          build_with_published_image,
          successful_build,
          failed_build,
      ], step_name='run builds.collect.buildbucket.get_multi (2)'),
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
      api.post_check(post_process.StatusSuccess),
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
  )
