# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules snapshot/postsubmit child builders and generates LKGM CL.

This recipe orchestrates the execution of child builders for snapshot and postsubmit
builds, runs any necessary hardware tests, and optionally generates a LKGM (Last
Known Good Manifest) uprev CL if the conditions are met. The recipe is designed
to work with both internal and external manifest repositories.
"""

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
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'git_footers',
    'greenness',
    'orch_menu',
    'snapshot_orch_menu',
    'src_state',
    'cros_snapshot',
    'cros_lkgm',
    'cros_version',
]

# Projects to be refered in this build.
_SYNC_PROJECTS = [
    # To read the current chromeos version.
    'src/third_party/chromiumos-overlay',
]

def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  with api.snapshot_orch_menu.setup_orchestrator(
      additional_sync_project=_SYNC_PROJECTS) as config:
    with api.step.nest('retrieving CrOS version') as presentation:
      version_str = api.cros_version.version.platform_version
      snapshot_identifier = api.cros_snapshot.snapshot_identifier()
      if snapshot_identifier:
        version_str += f'-{snapshot_identifier}'
      presentation.step_text = version_str

    if config:
      DoRunSteps(api)
    raw_result = api.snapshot_orch_menu.create_recipe_result()

    summary_markdown = f'Version: {version_str}'
    if api.greenness.greenness_markdown:
      summary_markdown += f'\n\n{api.greenness.greenness_markdown}'
    if raw_result.summary_markdown:
      summary_markdown += '\n\n'
      summary_markdown += raw_result.summary_markdown

    result = result_pb2.RawResult(status=raw_result.status,
                                  summary_markdown=summary_markdown)
    return result

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
  api.cros_lkgm.do_lkgm_via_pupr()
  # Run any HW tests.
  api.snapshot_orch_menu.plan_and_run_tests(testable_builds=testable_builds)

  with api.context(cwd=api.src_state.external_manifest.path):
    external_manifest_position = api.git_footers.position_num('HEAD')
    # The above method returns 1 on error.
    external_manifest_position = (0 if external_manifest_position == 1 else
                                  external_manifest_position)
  with api.context(cwd=api.src_state.internal_manifest.path):
    internal_manifest_position = api.git_footers.position_num('HEAD')
    # The above method returns 1 on error.
    internal_manifest_position = (0 if internal_manifest_position == 1 else
                                  internal_manifest_position)

  # Generate LKGM uprev CL if the condition meets.
  if snapshot_identifier:
    with api.step.nest('retrieving platform version') as presentation:
      version_str = api.cros_version.version.platform_version
      with api.step.nest('retrieving snapshot identifier') as presentation2:
        snapshot_identifier = api.cros_snapshot.snapshot_identifier()
        if snapshot_identifier:
          presentation2.step_text = snapshot_identifier
          version_str += f'-{snapshot_identifier}'

    with api.step.nest('generate a LKGM uprev CL') as presentation:
      if api.snapshot_orch_menu.should_generate_lkgm_cl(version_str):
        api.cros_lkgm.do_lkgm(
            builds_status.completed_builds, lkgm_version=version_str,
            internal_manifest_position=internal_manifest_position,
            external_manifest_position=external_manifest_position)
      else:
        presentation.step_text = 'Skipped generating a LKGM CL.'


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
      api.cros_snapshot.simulated_snapshot_identifier(111111),
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(
          True, step_name='generate a LKGM uprev CL'),
      api.post_check(post_process.MustRun,
                     'generate a LKGM uprev CL.call chrome_chromeos_lkgm'),
      collect_builds=green_build_results, with_manifest_refs=True,
      builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test(
      'lkgm-uprev-not-generated', data.ctp_normal, lfg_props,
      api.cros_snapshot.simulated_snapshot_identifier(111111),
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(
          False, step_name='generate a LKGM uprev CL'),
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
