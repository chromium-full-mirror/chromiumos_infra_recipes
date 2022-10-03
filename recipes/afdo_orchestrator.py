# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that generates artifacts using HW Test results.

All builders run against the same source tree.
"""

from recipe_engine import post_process

from PB.chromiumos.common import ArtifactsByService
from PB.recipes.chromeos.afdo_orchestrator import AfdoOrchestratorProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'orch_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = AfdoOrchestratorProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator() as config:
    if config:
      DoRunSteps(api, properties)
    return api.orch_menu.create_recipe_result()


def DoRunSteps(api, properties):

  # Run the child builders.
  api.orch_menu.plan_and_run_children()

  # If this is a dry run, check that the builds passed and quit.
  # TODO(crbug/1071440): Because the HW Tests have production side effects, we
  # must not run them for dryruns.
  if api.orch_menu.is_dry_run:
    return

  # Run any HW tests.
  builds_status = api.orch_menu.plan_and_run_tests()

  if not builds_status.fatal_failures and properties.process_child:
    # Create InputArtifactInfo for the CHROME_DEBUG_BINARY from the creating
    # builder.
    art_property = lambda b: b.output.properties['artifacts']
    locs = list(
        set('{}/{}'.format(
            art_property(b)['gs_bucket'],
            art_property(b)['gs_path'])
            for b in builds_status.testable_builds
            if art_property(b)['gs_bucket']))
    input_artifacts = [
        dict(artifact_types=[ArtifactsByService.Toolchain.CHROME_DEBUG_BINARY],
             gs_locations=locs)
    ]

    # Schedule and wait for any process_child builder.
    api.orch_menu.schedule_wait_build(
        properties.process_child,
        await_completion=True,
        properties=dict(input_artifacts=input_artifacts),
        check_failures=True,
        step_name='run {}'.format(properties.process_child),
        timeout_sec=4 * 60 * 60,
    )

  # Launch any specified follow on orchestrator.
  api.orch_menu.run_follow_on_orchestrator()


def GenTests(api):

  data = api.orch_menu.standard_test_data(
      extra_output_properties=dict(
          artifacts=dict(
              files_by_artifact={"CHROME_DEBUG_BINARY": ["chrome.debug.bz2"]},
              gs_bucket="chromeos-image-archive", gs_path="GS_PATH/DIR")))

  yield api.orch_menu.test('basic', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_history=True, collect_builds=data.builds)

  find_inflight_name = 'find inflight orchestrator'
  wait_inflight_name = '%s.waiting for existing runs.wait' % find_inflight_name
  yield api.orch_menu.test(
      'join-if-inflight-orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[data.inflight_orchestrator],
      cq=True, with_history=True)

  yield api.orch_menu.test(
      'runs-if-no-inflight-orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, find_inflight_name),
      api.post_check(post_process.DoesNotRun,
                     wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[], cq=True, with_history=True)

  yield api.orch_menu.test('dry-run',
                           api.post_check(post_process.DoesNotRun, 'run tests'),
                           api.post_check(post_process.StatusSuccess), cq=True,
                           dry_run=True, collect_builds=data.builds,
                           with_history=True, git_footers=[])

  yield api.orch_menu.test(
      'orchestrator-with-process-child-and-followon', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.properties(process_child='benchmark-afdo-process'),
      collect_builds=data.builds, process_child=data.process_child,
      follow_on_orch=data.follow_on_orchestrator, bucket='toolchain',
      builder='orderfile-generate-orchestrator', with_history=True,
      git_footers=[])
