# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

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
      api.step_data(
          'bump version.commit chromeos/config/chromeos_version.sh.check version change reflected on remote.read remote version.read chromeos_version.sh',
          api.file.read_text(
              text_content=api.cros_version.chromeos_version_contents(
                  'R99-1234.55.0'))),
      api.post_check(
          post_process.MustRun,
          'bump version.commit chromeos/config/chromeos_version.sh.check version change reflected on remote (2)'
      ),
  )

  yield api.test(
      'release-branch',
      orchestrator(git_ref='refs/heads/release-R87-13505.B'),
  )

  yield api.test(
      'stabilize-branch',
      orchestrator(git_ref='refs/heads/stabilize-13505.33.B'),
  )

  yield api.test(
      'staging',
      orchestrator(builder='staging-release-main-orchestrator'),
      api.post_check(
          post_process.MustRun,
          'bump version.commit chromeos/config/chromeos_version.sh.abandon CL 1.gerrit abandon'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'bump version.commit chromeos/config/chromeos_version.sh.check version change reflected on remote'
      ),
      api.post_check(
          post_process.MustRun,
          'bump version.commit chromeos/config/chromeos_version.sh.reset to remote branch'
      ),
  )
