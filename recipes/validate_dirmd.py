# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to validate DIR_METADATA files in the ChromeOS source tree.

This recipe will call `dirmd validate` and `test_plan validate` on DIR_METADATA
files in projects touched by the input CLs.
"""

from recipe_engine import post_process

DEPS = [
    'depot_tools/depot_tools',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/step',
    'cros_test_plan_v2',
    'dirmd',
    'failures',
    'repo',
    'urls',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.workspace_util.setup_workspace(), api.workspace_util.sync_to_commit(
  ):
    api.workspace_util.apply_changes()
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
    failures = []
    for pi in project_infos:
      with api.step.nest('validate {}'.format(pi.name)):
        full_path = api.workspace_util.workspace_path.join(pi.path)
        try:
          api.dirmd.validate_dir(full_path)
        except api.step.StepFailure as ex:
          # We want to link to the stdout of the actual step that failed, not
          # the nested step created above, so set use_top_level_step=False.
          logdog_url = api.urls.get_logdog_url(ex.result, 'stdout',
                                               use_top_level_step=False)
          failures.append(
              api.failures.Failure(
                  kind='dirmd validation',
                  title=pi.name,
                  link_map={'stdout': logdog_url},
                  fatal=True,
                  id=pi.name,
              ))

        try:
          api.cros_test_plan_v2.validate(full_path)
        except api.step.StepFailure as ex:
          # We want to link to the stdout of the actual step that failed, not
          # the nested step created above, so set use_top_level_step=False.
          logdog_url = api.urls.get_logdog_url(ex.result, 'stdout',
                                               use_top_level_step=False)
          failures.append(
              api.failures.Failure(
                  kind='test_plan validation',
                  title=pi.name,
                  link_map={'stdout': logdog_url},
                  fatal=True,
                  id=pi.name,
              ))

    return api.failures.aggregate_failures(failures)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
  )

  # Populate logdog fields on the build message so link components are filled
  # out.
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  # Step data for dirmd and test_plan validation failures.
  dirmd_glob_paths = api.step_data(
      'validate project-a.dirmd validate [CLEANUP]/chromiumos_workspace/src/project-a.find DIR_METADATA files',
      api.file.glob_paths(['a/b/DIR_METADATA']),
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
      api.post_check(post_process.StatusFailure),
      api.post_check(
          post_process.ResultReason,
          '1 dirmd validation failed\n\n- project-a: [stdout](https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/validate_project-a/dirmd_validate_[CLEANUP]_chromiumos_workspace_src_project-a/dirmd_validate/stdout)'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'test_plan validation failure',
      api.buildbucket.build(build_message),
      test_plan_validation_fail,
      api.post_check(post_process.StatusFailure),
      api.post_check(
          post_process.ResultReason,
          '1 test_plan validation failed\n\n- project-a: [stdout](https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/validate_project-a/test_plan_validate_[CLEANUP]_chromiumos_workspace_src_project-a/stdout)'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'dirmd and test_plan validation failures',
      api.buildbucket.build(build_message),
      dirmd_glob_paths,
      dirmd_validation_fail,
      test_plan_validation_fail,
      api.post_check(post_process.StatusFailure),
      api.post_check(
          post_process.ResultReasonRE,
          '(?s)1 dirmd validation failed.*1 test_plan validation failed.*'),
      api.post_process(post_process.DropExpectation),
  )
