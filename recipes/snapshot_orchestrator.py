# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules snapshot/postsubmit child builders and watches for failures."""

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.cros_snapshot.cros_snapshot import CrosSnapshotProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'orch_menu',
    'snapshot_orch_menu',
    'cros_snapshot',
    'cros_lkgm',
]

# Set the LGKM uprev freqency as every 12 snapshots (= 6 hours).
SNAPSHOT_LGKM_UPREV_FREQUENCY = 12


def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  with api.snapshot_orch_menu.setup_orchestrator() as config:
    if config:
      DoRunSteps(api)

    return api.snapshot_orch_menu.create_recipe_result()


def DoRunSteps(api: RecipeApi):
  snapshot_identifier = api.cros_snapshot.snapshot_identifier()

  # Run the child builders.
  extra_child_props = {}
  extra_child_props['$chromeos/metadata'] = {
      'sources_gitiles_commit_override':
          MessageToDict(api.build_menu.resultdb_gitiles_commit)
  }
  extra_child_props['$chromeos/cros_snapshot'] = MessageToDict(
      CrosSnapshotProperties(snapshot_identifier=snapshot_identifier))
  builds_status = api.snapshot_orch_menu.plan_and_run_children(
      extra_child_props=extra_child_props,
  )

  testable_builds = builds_status.testable_builds
  # Run any HW tests.
  api.snapshot_orch_menu.plan_and_run_tests(testable_builds=testable_builds)

  # Generate LKGM uprev CL if the condition meets.
  if snapshot_identifier:
    with api.step.nest('generate a LKGM uprev CL') as presentation:
      if int(snapshot_identifier) % SNAPSHOT_LGKM_UPREV_FREQUENCY == 0:
        api.cros_lkgm.do_lkgm(builds_status.completed_builds, use_snapshot=True)
      else:
        presentation.step_text = (
            f'Skipped. A CL is generated only every {SNAPSHOT_LGKM_UPREV_FREQUENCY} runs'
        )


def GenTests(api: RecipeTestApi):

  data = api.snapshot_orch_menu.standard_test_data()
  lfg_props = api.properties(
      **{
          '$chromeos/greenness': {
              'publish_property': True
          },
          '$chromeos/cros_lkgm': {
              'enable_lkgm': True,
              'full_run': True
          }
      })

  collect, collect_after = api.orch_menu.orch_child_builds(
      'snapshot-orchestrator', '-snapshot')
  green_build_results = collect + collect_after
  schedule_builds_test_data = []
  for build in green_build_results:
    schedule_builds_test_data.append(
        api.buildbucket.simulated_schedule_output(
            builds_service_pb2.BatchResponse(responses=[{
                'schedule_build': build
            }]),
            'run builds.schedule new builds.{}'.format(build.builder.builder)))

  yield api.snapshot_orch_menu.test('basic', data.ctp_normal, lfg_props,
                                    *schedule_builds_test_data,
                                    with_history=True,
                                    collect_builds=green_build_results,
                                    with_manifest_refs=True,
                                    builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test(
      'lkgm-uprev-generated', data.ctp_normal, lfg_props,
      api.cros_snapshot.simulated_snapshot_identifier(
          SNAPSHOT_LGKM_UPREV_FREQUENCY),
      api.post_check(post_process.MustRun,
                     'generate a LKGM uprev CL.call chrome_chromeos_lkgm'),
      collect_builds=green_build_results, with_manifest_refs=True,
      builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test(
      'lkgm-uprev-not-generated', data.ctp_normal, lfg_props,
      api.cros_snapshot.simulated_snapshot_identifier(
          SNAPSHOT_LGKM_UPREV_FREQUENCY + 1),
      api.post_check(post_process.DoesNotRun,
                     'generate a LKGM uprev CL.call chrome_chromeos_lkgm'),
      collect_builds=green_build_results, with_manifest_refs=True,
      builder='snapshot-orchestrator')

  crit_failure_build_results = collect + collect_after
  for b in crit_failure_build_results:
    if b.builder.builder == 'amd64-generic-snapshot':
      b.status = common_pb2.FAILURE
  yield api.snapshot_orch_menu.test(
      'critical-child-builder-fails', data.ctp_normal, lfg_props,
      *schedule_builds_test_data, with_manifest_refs=True,
      collect_builds=crit_failure_build_results, status='FAILURE',
      builder='snapshot-orchestrator')

  collect, collect_after = api.orch_menu.orch_child_builds(
      'snapshot-orchestrator', '-snapshot')
  non_crit_failure_build_results = collect + collect_after
  for b in non_crit_failure_build_results:
    if b.builder.builder == 'grunt-snapshot':
      b.status = common_pb2.FAILURE
  yield api.snapshot_orch_menu.test(
      'non-critical-child-builder-fails', data.ctp_normal, lfg_props,
      with_manifest_refs=True, collect_builds=non_crit_failure_build_results,
      builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test(
      'missing-gitiles-commit',
      data.ctp_normal,
      lfg_props,
      api.post_check(post_process.MustRun,
                     'update manifest-internal ref refs/heads/postsubmit'),
      revision=None,
      with_manifest_refs=True,
  )
