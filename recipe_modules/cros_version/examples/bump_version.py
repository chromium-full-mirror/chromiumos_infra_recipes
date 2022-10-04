# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/file',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_version',
    'src_state',
    'test_util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.cros_infra_config.configure_builder()
  with api.workspace_util.setup_workspace():
    staging = api.cros_infra_config.is_staging
    api.workspace_util.sync_to_commit(staging=staging)
    api.cros_version.bump_version(dry_run=staging)


def GenTests(api):

  def orchestrator(**kwargs):
    kwargs.setdefault('bucket', 'release')
    kwargs.setdefault('builder', 'release-main-orchestrator')
    kwargs.setdefault('git_ref', 'refs/heads/main')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_orchestrator(**kwargs).build

  yield api.test(
      'basic',
      orchestrator(),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} prod']),
  )

  yield api.test(
      'release-branch',
      orchestrator(git_ref='refs/heads/release-R87-13505.B'),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} prod']),
  )

  yield api.test(
      'stabilize-branch',
      orchestrator(git_ref='refs/heads/stabilize-13505.33.B'),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} prod']),
  )

  yield api.test(
      'staging',
      orchestrator(builder='staging-release-main-orchestrator'),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} staging']),
  )

  yield api.test(
      'with-ref',
      orchestrator(),
      api.properties(
          **{
              "$chromeos/cros_version": {
                  "version_bumper_cipd_package": "version_bumper_foo",
                  "version_bumper_cipd_ref": "bar",
              }
          }),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['version_bumper_foo bar']),
  )
