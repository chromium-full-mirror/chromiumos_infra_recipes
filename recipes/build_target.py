# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_artifacts',
    'cros_bisect',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'dev',
    'gerrit',
    'infra_config',
    'overlayfs',
    'repo',
    'sync_chrome',
]

from recipe_engine.config import Dict
from recipe_engine.recipe_api import Property

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget

PROPERTIES = {
    'build_target': Property(kind=Dict()),

    # Whether or not to build an image.
    'build_image': Property(kind=bool, default=True),

    # Whether or not to upload build/test artifacts.
    'upload_artifacts': Property(kind=bool, default=False),

    # Whether or not to upload binary prebuilts to Google Storage.
    'upload_prebuilts': Property(kind=bool, default=False),

    # Whether or not to run the chromite tests and exit early.
    'run_chromite_tests': Property(kind=bool, default=False),
}

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]


def _run_cros_sdk_script(api, script, target, builder_config, *args):
  # TODO: Replace with Build API equivalents.
  cmd = ['/mnt/host/source/src/scripts/%s' % script, '--board', target]
  if args:
    cmd.extend(args)

  env = {}
  # TODO(crbug.com/950614): Most (internal) boards are able to find Chrome
  # prebuilts w/o this USE flag. Remove if it is not needed.
  if builder_config.chrome.internal:
    env['USE'] = 'chrome_internal'

  api.cros_sdk.run(script, cmd, env)


def _apply_gerrit_changes(api, gerrit_changes):
  with api.step.nest('apply cherry-pick changes'):
    patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
    api.cros_source.apply_gerrit_patch_sets(patch_sets)


def RunSteps(api, build_target, build_image, upload_artifacts,
             upload_prebuilts, run_chromite_tests):
  # TODO(evanhernandez): Many bots in the Chrome OS fleet have corrupted gsutil
  # creds lock thanks to some incorrectly privileged code. As a hack around this
  # problem, delete the creds lock before starting execution.
  # Remove this after ~2 weeks.
  api.step('remove stale gsutil cache',
           ['sudo', 'rm', '-rf', '/home/chrome-bot/.gsutil'])

  build_target = BuildTarget(**build_target)
  build_config = api.infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)

  api.cros_bisect.set_bisect_builder(build_target.name)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      # Sync workspace to gitiles_commit manifest snapshot.
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      if api.buildbucket.build.input.gerrit_changes:
        _apply_gerrit_changes(api, api.buildbucket.build.input.gerrit_changes)

      # Use a named cache for the chroot.
      api.cros_sdk.configure(
          chroot_parent_path=api.path['cache'].join('cros_chroot'))

      if run_chromite_tests:
        api.cros_sdk.run('run_tests', ['/mnt/host/source/chromite/run_tests'])
        return

      _run_cros_sdk_script(api, 'setup_board', build_target.name, build_config)

      # TODO(seanabraham): We should always run through the cros_relevance code,
      # even when there are no gerrit_changes. This is a temporary way to
      # unblock postsubmit orchestrator, since is_build_pointless currently
      # always fails :/.
      if api.buildbucket.build.input.gerrit_changes:
        if api.cros_relevance.is_build_pointless(api.buildbucket.build, build_target):
          return

      # Packages subset will be present when FindIt asks for bisection build.
      packages = api.cros_bisect.get_packages()
      _run_cros_sdk_script(api, 'build_packages', build_target.name,
                           build_config, *packages)

      if build_image:
        _run_cros_sdk_script(api, 'build_image', build_target.name,
                             build_config, 'test')

      if upload_artifacts:
        # TODO(crbug.com/905039): Stop using dummy artifact kind.
        api.cros_artifacts.upload_artifacts(
            'upload dummy artifacts', build_target, 'dummy',
            build_config.artifacts.artifact_types)

      prebuilts = build_config.artifacts.prebuilts
      if upload_prebuilts and prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
        # TODO(crbug.com/920418): Stop using dummy binhost.
        api.cros_prebuilts.upload_target_prebuilts(
            build_target, 'dummy',
            private=(prebuilts == BuilderConfig.Artifacts.PRIVATE))


def GenTests(api):
  yield (api.test('basic') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('upload-artifacts') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        upload_artifacts=True))

  yield (api.test('upload-prebuilts') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        upload_prebuilts=True))

  yield (api.test('with-findit-bisect') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(
             build_target={'name': 'amd64-generic'},
             findit_bisect={'targets': ['foo', 'bar', 'baz']},
             build_image=False,
         ))

  yield (api.test('with-gerrit-changes') +  #
         api.cros_relevance.simulate_run_pointless_build_checker() +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-chromite-tests') + #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='chromite-cq') +  #
         api.properties(build_target={'name': 'chromite'},
                        run_chromite_tests=True))

  yield (api.test('pointless-build') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             build_is_pointless=True) +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))
