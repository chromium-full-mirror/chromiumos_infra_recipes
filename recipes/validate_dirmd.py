# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to validate DIR_METADATA files in the ChromeOS source tree.

This recipe will call `dirmd validate` and `test_plan validate` on DIR_METADATA
files in projects touched by the input CLs.
"""

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

DEPS = [
    'depot_tools/depot_tools',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_plan_v2',
    'dirmd',
    'failures',
    'repo',
    'urls',
    'workspace_util',
]



def RunSteps(api):
  with api.workspace_util.setup_workspace(), api.workspace_util.sync_to_commit(
  ):
    api.workspace_util.apply_changes(ignore_missing_projects=True)

    if not api.workspace_util.patch_sets:
      return result_pb2.RawResult(
          status=common_pb2.SUCCESS,
          summary_markdown='No patchsets applied (possibly because input GerritChanges are not in a project / branch in the manifest)'
      )

    # Get the ProjectInfos of the input patch sets, de-duped and sorted.
    project_infos = sorted(
        set(
            api.repo.project_infos(
                projects=[
                    patch.project for patch in api.workspace_util.patch_sets
                ],
            )))


    # For each project, try both dirmd and test_plan validation. Catch step
    # step failures and turn them into failures.Failure objects with links to
    # the stdout of the failed calls, then call failures.aggregate_failures. The
    # motivation is
    # 1. aggregate_failures presents a nice summary markdown, so users can
    #    immediately see which projects failed and go to the failed stdout,
    #    without needing to investigate individual steps.
    # 2. To present all failures from a run, not just the first failed
    #    validation.
    validation_kinds = ['dirmd validation', 'test_plan validation']
    results = api.failures.Results(
        failures=[], successes={
            validation_kinds[0]: 0,
            validation_kinds[1]: 0
        })
    for pi in project_infos:
      with api.step.nest('validate {}'.format(pi.name)):
        full_path = api.workspace_util.workspace_path / pi.path
        kind = validation_kinds[0]
        try:
          api.dirmd.validate_dir(full_path)
          results.successes[kind] += 1
        except api.step.StepFailure as ex:
          # We want to link to the stdout of the actual step that failed, not
          # the nested step created above, so set use_top_level_step=False.
          logdog_url = api.urls.get_logdog_url(ex.result, 'stdout',
                                               use_top_level_step=False)
          results.failures.append(
              api.failures.Failure(
                  kind=kind,
                  title=pi.name,
                  link_map={'stdout': logdog_url},
                  fatal=True,
                  id=pi.name,
              ))

        kind = validation_kinds[1]
        try:
          api.cros_test_plan_v2.validate(full_path)
          results.successes[kind] += 1
        except api.step.StepFailure as ex:
          # We want to link to the stdout of the actual step that failed, not
          # the nested step created above, so set use_top_level_step=False.
          logdog_url = api.urls.get_logdog_url(ex.result, 'stdout',
                                               use_top_level_step=False)
          results.failures.append(
              api.failures.Failure(
                  kind=kind,
                  title=pi.name,
                  link_map={'stdout': logdog_url},
                  fatal=True,
                  id=pi.name,
              ))

    return api.failures.aggregate_failures(results)


def GenTests(api):
  # Populate logdog fields on the build message so link components are filled
  # out.
  build_message = api.buildbucket.try_build_message(
      build_id=123, gerrit_changes=[
          common_pb2.GerritChange(
              host='https://chromium-review.googlesource.com',
              project='project-a', change=123, patchset=4),
      ])
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test(
      'basic',
      api.buildbucket.build(build_message),
  )

  # Step data for dirmd and test_plan validation failures.
  dirmd_glob_paths = api.step_data(
      'validate project-a.dirmd validate [CLEANUP]/chromiumos_workspace/src/project-a.find DIR_METADATA files',
      stdout=api.raw_io.output('a/b/DIR_METADATA'),
  )
  dirmd_validation_fail = api.step_data(
      'validate project-a.dirmd validate [CLEANUP]/chromiumos_workspace/src/project-a.dirmd validate',
      retcode=1)
  test_plan_validation_fail = api.step_data(
      'validate project-a.test_plan validate [CLEANUP]/chromiumos_workspace/src/project-a',
      retcode=1)

  yield api.test(
      'dirmd validation failure',
      api.buildbucket.build(build_message),
      dirmd_glob_paths,
      dirmd_validation_fail,
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 1 dirmd validation failed.*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'test_plan validation failure',
      api.buildbucket.build(build_message),
      test_plan_validation_fail,
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 1 test_plan validation failed.*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'dirmd and test_plan validation failures',
      api.buildbucket.build(build_message),
      dirmd_glob_paths,
      dirmd_validation_fail,
      test_plan_validation_fail,
      api.post_check(post_process.ResultReasonRE,
                     '.*1 out of 1 dirmd validation failed.*'),
      api.post_check(post_process.ResultReasonRE,
                     '.*1 out of 1 test_plan validation failed.*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'all input changes discarded',
      api.buildbucket.build(build_message),
      api.repo.project_infos_step_data(
          'cherry-pick gerrit changes.apply gerrit patch sets', [{
              'project': 'otherproject'
          }]),
      api.post_process(post_process.DropExpectation),
  )
