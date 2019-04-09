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
}

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]


def _run_cros_sdk_script(api, script, target, *args):
  # TODO: Replace with Build API equivalents.
  cmd = ['/mnt/host/source/src/scripts/%s' % script, '--board', target]
  if args:
    cmd.extend(args)
  api.cros_sdk.run(script, cmd)


def RunSteps(api, build_target, build_image, upload_artifacts,
             upload_prebuilts):
  build_target_name = build_target['name']
  build_config = api.infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)

  api.cros_bisect.set_bisect_builder(build_target_name)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      # Sync workspace to gitiles_commit manifest snapshot.
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      # Use a named cache for the chroot.
      api.cros_sdk.configure(
          chroot_parent_path=api.path['cache'].join('cros_chroot'))

      _run_cros_sdk_script(api, 'setup_board', build_target_name)

      # Packages subset will be present when FindIt asks for bisection build.
      packages = api.cros_bisect.get_packages()
      _run_cros_sdk_script(api, 'build_packages', build_target_name, *packages)

      if build_image:
        _run_cros_sdk_script(api, 'build_image', build_target_name)

      if upload_artifacts:
        # TODO(crbug.com/905039): Read artifacts to upload from BuilderConfig.
        artifacts_bucket, artifacts_path = api.cros_artifacts.upload_artifacts(
            'upload dummy artifacts', BuildTarget(name=build_target_name),
            'dummy', [
                'image-zip',
                'autotest-files',
                'tast-files',
                'pinned-guest-images',
                'firmware',
                'ebuild-logs',
            ])
        res = api.step('set output artifacts', cmd=None)
        res.presentation.properties['artifacts'] = {
            'gs_bucket': artifacts_bucket,
            'gs_path': artifacts_path,
            # TODO(evanhernandez): Also output dict mapping artifact type to
            # file name.
        }

      prebuilts = build_config.artifacts.prebuilts
      if upload_prebuilts and prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
        # TODO(crbug.com/920418): Stop using dummy binhost.
        api.cros_prebuilts.upload_target_prebuilts(
            BuildTarget(name=build_target_name), 'dummy',
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
