# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing the incremental recipe_module."""

# pylint: disable=import-error
from PB.recipe_modules.chromeos.incremental.incremental import IncrementalProperties
from PB.chromiumos.builder_config import BuilderConfig
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_prebuilts',
    'cros_sdk',
    'cros_source',
    'easy',
    'git',
    'incremental',
    'repo',
    'src_state',
]



def RunSteps(api):
  builder_config = BuilderConfig(id=BuilderConfig.Id(name='test'),)

  cwd = api.cros_source.workspace_path
  repo_path = cwd.join('.repo')
  api.file.ensure_directory('repo dir', repo_path)

  inc_props = IncrementalProperties(**{
      'cop_enabled': True,
      'build_time_delta': '7.days.ago',
      'use_llfg': False,
  })
  api.incremental.DoOldBuild(api, builder_config, inc_props)

  # llfg run
  inc_props.use_llfg = True
  api.incremental.DoOldBuild(api, builder_config, inc_props)


def GenTests(api):
  yield api.test(
      'inc-build-non-llfg',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'repo sync'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.MustRun, 'create sysroot'),
      api.post_check(post_process.MustRun, 'repo sync (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'Disable cros clean-outdated-pkgs'),
      build_target='amd64-generic',
      status='SUCCESS',
  )

  yield api.test(
      'inc-build-llfg',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun, 'repo sync (3)'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.MustRun, 'create sysroot (2)'),
      api.post_check(post_process.MustRun, 'Apply LLFG manifest snapshot'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'Disable cros clean-outdated-pkgs'),
      build_target='amd64-generic',
      status='SUCCESS',
  )
