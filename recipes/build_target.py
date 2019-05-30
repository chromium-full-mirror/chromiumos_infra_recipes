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
    'cros_build_api',
    'cros_infra_config',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'cros_version',
    'failures',
    'gerrit',
    'portage',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import TEST
from PB.chromiumos.common import PackageInfo
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import Image
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromite.api.test import ChromiteUnitTestRequest
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

PROPERTIES = BuildTargetProperties

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]


def RunSteps(api, properties):
  build_target = properties.build_target
  build_config = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)
  gitiles_commit = api.buildbucket.gitiles_commit
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  api.cros_bisect.set_bisect_builder(build_target.name)

  # Do a preliminary pointless build check prior to setup_board.
  if api.cros_relevance.is_build_pointless(
      api.buildbucket.build, build_target, dep_graph_check=False,
      name='pre-sync pointless build check'):
    return

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(gitiles_commit)

      if gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      # TODO(evanhernandez): Replace with build API call.
      api.portage.uprev_packages(boards=[build_target.name])

      with api.step.nest('init sdk') as step:
        response = api.cros_build_api.SdkService.Create(
            CreateSdkRequest(
                flags=CreateSdkRequest.Flags(no_replace=True,
                                             no_use_image=True),
                chroot=api.cros_sdk.chroot))
        step.presentation.logs['sdk version'] = [str(response.version.version)]
        # TODO(crbug.com/949721): Currently, chromite depends on the chroot
        # living within the source tree. As a workaround, link the external
        # chroot the workspace to make it look legit. New chromite services
        # should accept the chroot path as a parameter.
        api.cros_sdk.link_chroot(api.cros_source.workspace_path)

      api.cros_build_api.SdkService.Update(
          UpdateSdkRequest(chroot=api.cros_sdk.chroot,
                           toolchain_targets=[build_target]), name='update sdk')

      with api.step.nest('create sysroot'):
        profile = None
        if build_config.build.portage_profile.profile:
          profile = Profile(name=build_config.build.portage_profile.profile)
        create_sysroot_response = api.cros_build_api.SysrootService.Create(
            SysrootCreateRequest(build_target=build_target,
                                 profile=profile,
                                 chroot=api.cros_sdk.chroot))
        sysroot = create_sysroot_response.sysroot

      if api.cros_relevance.is_build_pointless(
          api.buildbucket.build, build_target,
          name='post-sync pointless build check'):
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
            InstallPackagesRequest(sysroot=sysroot, packages=packages,
                                   use_flags=build_config.build.use_flags))
        api.cros_bisect.set_build_compile_failure(response.failed_packages)
        api.failures.raise_failed_packages(response.failed_packages)

      image_types = build_config.build.image_types
      if image_types:
        with api.step.nest('build image'):
          version = api.cros_version.read_workspace_version()
          response = api.cros_build_api.ImageService.Create(
              CreateImageRequest(
                  build_target=build_target, chroot=api.cros_sdk.chroot,
                  image_types=image_types,
                  builder_path='%s/%s' % (build_config.id.name, version)),
              timeout=45 * 60)
          api.failures.raise_failed_packages(response.failed_packages)

      if build_config.unit_tests.ebuilds_run_spec in [BuilderConfig.RUN,
                                                      BuilderConfig.RUN_EXIT]:
        with api.step.nest('run ebuild tests'):
          response = api.cros_build_api.TestService.BuildTargetUnitTest(
              BuildTargetUnitTestRequest(
                  build_target=build_target, chroot=api.cros_sdk.chroot,
                  result_path=str(api.path.mkdtemp()),
                  package_blacklist=build_config.unit_tests.package_blacklist))
          api.failures.raise_failed_packages(response.failed_packages)

      if build_config.unit_tests.ebuilds_run_spec == BuilderConfig.RUN_EXIT:
        return

      artifact_types = build_config.artifacts.artifact_types
      if artifact_types:
        api.cros_artifacts.upload_artifacts(
            'upload artifacts', build_target, build_config.id.type,
            build_config.artifacts.artifacts_gs_bucket, artifact_types)

      prebuilts = build_config.artifacts.prebuilts
      if prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
        api.cros_prebuilts.upload_target_prebuilts(
            build_target, build_config.id.type,
            build_config.artifacts.prebuilts_gs_bucket,
            private=(prebuilts == BuilderConfig.Artifacts.PRIVATE))

def GenTests(api):
  yield (api.test('basic') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('with-findit-bisect') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +
         api.properties(
             **{'build_target': {'name': 'amd64-generic'},
                '$chromeos/cros_bisect': CrosBisectProperties(targets=[
                    api.cros_bisect.serialized_package_info('foo', 'cat1', '1'),
                    api.cros_bisect.serialized_package_info('bar', 'cat1', '2'),
                    api.cros_bisect.serialized_package_info('baz', 'cat2', '3'),
                ])}))

  yield (api.test('with-gerrit-changes') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-ebuild-tests') +  #
         api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                   builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-exit-ebuild-tests') +  #
         api.buildbucket.try_build(
             project='chromeos',
             bucket='postsubmit',
             builder='grunt-unittest-only-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +
         api.properties(build_target={'name': 'grunt'}))

  yield (api.test('pointless-build-first-check') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check',
             build_is_pointless=True) +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('pointless-build-second-check') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='pre-sync pointless build check') +
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check',
             build_is_pointless=True) +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))
