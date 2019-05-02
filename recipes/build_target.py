# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_artifacts',
    'cros_bisect',
    'cros_build_api',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'failures',
    'gerrit',
    'infra_config',
]

from recipe_engine.config import Dict
from recipe_engine.recipe_api import Property

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import Image
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.test import ChromiteUnitTestRequest


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


def RunSteps(api, build_target, build_image, upload_artifacts,
             upload_prebuilts, run_chromite_tests):
  build_target = BuildTarget(**build_target)
  build_config = api.infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)
  gitiles_commit = api.buildbucket.gitiles_commit
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  api.cros_bisect.set_bisect_builder(build_target.name)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(gitiles_commit)

      if gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      if run_chromite_tests:
        api.cros_build_api.TestService.ChromiteUnitTest(
            ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot))
        return

      with api.step.nest('create sysroot'):
        sysroot = api.cros_build_api.SysrootService.Create(
            SysrootCreateRequest(build_target=build_target,
                                 chroot=api.cros_sdk.chroot)).sysroot

      if api.cros_relevance.is_build_pointless(api.buildbucket.build, build_target):
        return

      with api.step.nest('install toolchain'):
        response = api.cros_build_api.SysrootService.InstallToolchain(
            InstallToolchainRequest(sysroot=sysroot,
                                    chroot=api.cros_sdk.chroot))
        api.failures.raise_failed_packages(response.failed_packages)

      with api.step.nest('install packages'):
        # Packages subset will be present when FindIt asks for bisection build.
        packages = api.cros_bisect.get_packages()
        response = api.cros_build_api.SysrootService.InstallPackages(
            InstallPackagesRequest(sysroot=sysroot, packages=packages))
        api.failures.raise_failed_packages(response.failed_packages)

      if build_image:
        with api.step.nest('build image'):
          response = api.cros_build_api.ImageService.Create(
              CreateImageRequest(build_target=build_target,
                                 chroot=api.cros_sdk.chroot,
                                 image_types=[Image.TEST]))
          api.failures.raise_failed_packages(response.failed_packages)

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
         api.cros_relevance.simulate_run_pointless_build_checker() +
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('upload-artifacts') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker() +
         api.properties(build_target={'name': 'amd64-generic'},
                        upload_artifacts=True))

  yield (api.test('upload-prebuilts') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker() +
         api.properties(build_target={'name': 'amd64-generic'},
                        upload_prebuilts=True))

  yield (api.test('with-findit-bisect') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker() +
         api.properties(
             build_target={'name': 'amd64-generic'},
             findit_bisect={'targets': [
                 api.cros_bisect.serialized_package_info('foo', 'cat1', '1'),
                 api.cros_bisect.serialized_package_info('bar', 'cat1', '2'),
                 api.cros_bisect.serialized_package_info('baz', 'cat2', '3'),
             ]},
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
