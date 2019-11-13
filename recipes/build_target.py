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
    'chrome',
    'cros_artifacts',
    'cros_bisect',
    'cros_build_api',
    'cros_infra_config',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'cros_version',
    'easy',
    'failures',
    'gerrit',
    'goma',
    'portage',
]

from google.protobuf import json_format as json_pb

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import BASE
from PB.chromiumos.common import PackageInfo
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import Image
from PB.chromite.api.image import TestImageRequest
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.packages import UprevPackagesRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromite.api.test import ChromiteUnitTestRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

PROPERTIES = BuildTargetProperties

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]


def RunSteps(api, properties):
  build_target = properties.build_target
  gitiles_commit = api.buildbucket.gitiles_commit
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  with api.step.nest('read builder config') as step:
    try:
      build_config = api.cros_infra_config.get_builder_config(
          api.buildbucket.build.builder.builder)
    except LookupError:
      step.presentation.step_text = 'config not found, assuming deleted'
      return

  api.cros_bisect.set_bisect_builder(build_target.name)
  api.cros_sdk.set_use_flags(build_config.build.use_flags)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), \
      api.cros_sdk.cleanup_context(
          checkout_path=api.cros_source.workspace_path), \
      api.context(cwd=api.cros_source.workspace_path):
    DoRunSteps(api, build_target, build_config, gitiles_commit, gerrit_changes)

def DoRunSteps(api, build_target, build_config, gitiles_commit, gerrit_changes):
  api.cros_source.sync_snapshot(gitiles_commit)

  if gerrit_changes and build_config.build.apply_gerrit_changes:
    with api.step.nest('cherry-pick gerrit changes'):
      patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
      api.cros_source.apply_gerrit_patch_sets(patch_sets)

  with api.step.nest('uprev packages') as step:
    request = UprevPackagesRequest(
        chroot=api.cros_sdk.chroot,
        build_targets=[BuildTarget(name=build_target.name)],
        overlay_type=OVERLAYTYPE_BOTH)
    response = api.cros_build_api.PackageService.Uprev(request)

  with api.step.nest('init sdk') as step:
    api.cros_sdk.build_chmod_chroot()
    response = api.cros_build_api.SdkService.Create(
        CreateSdkRequest(
            flags=CreateSdkRequest.Flags(no_replace=True, no_use_image=True),
            chroot=api.cros_sdk.chroot))
    step.presentation.logs['sdk version'] = [str(response.version.version)]
    api.cros_sdk.link_chroot(api.cros_source.workspace_path)

  with api.step.nest('update sdk'):
    api.cros_build_api.SdkService.Update(
        UpdateSdkRequest(chroot=api.cros_sdk.chroot,
                         toolchain_targets=[build_target]))

  with api.step.nest('create sysroot'):
    profile = None
    if build_config.build.portage_profile.profile:
      profile = Profile(name=build_config.build.portage_profile.profile)
    create_sysroot_response = api.cros_build_api.SysrootService.Create(
        SysrootCreateRequest(
            build_target=build_target, profile=profile,
            chroot=api.cros_sdk.chroot, flags=SysrootCreateRequest.Flags(
                chroot_current=True, replace=True)))
    sysroot = create_sysroot_response.sysroot

  # Skip the pointless build check for kernel builders due to dep service bug.
  # TODO(https://crbug.com/1019562): bring the check back for all builders.
  if '-kernel-v' not in api.buildbucket.build.builder.builder:
    if api.cros_relevance.is_build_pointless(
        gerrit_changes, gitiles_commit, build_target=build_target,
        chroot=api.cros_sdk.chroot, name='post-sync pointless build check'):
      return

  try:
    api.easy.set_property_step('target_versions',
                               get_target_versions(api, build_target))
  except:  # pragma: no cover
    # Failing on kernel buildtest builders, see https://crbug.com/1017583.
    pass

  with api.step.nest('install toolchain'):
    flags = InstallToolchainRequest.Flags(
        compile_source=build_config.build.compile_toolchain)
    response = api.cros_build_api.SysrootService.InstallToolchain(
        InstallToolchainRequest(sysroot=sysroot, chroot=api.cros_sdk.chroot,
                                flags=flags))
    api.failures.raise_failed_packages(response.failed_packages)

  packages = get_packages(api, build_config)
  install_packages = build_config.build.install_packages
  if api.cros_infra_config.should_run(install_packages):
    if api.chrome.builds_chrome_from_source(build_target=build_target,
                                            chroot=api.cros_sdk.chroot,
                                            packages=packages):
      chrome_root = api.path['start_dir'].join('chrome')
      api.chrome.sync(chrome_root, api.cros_sdk.chroot, build_target,
                      build_config.chrome.internal)
      api.cros_sdk.set_chrome_root(str(chrome_root))
      api.cros_sdk.set_goma_config(str(api.goma.goma_dir),
                                   str(api.goma.goma_client_json),
                                   api.goma.goma_approach)

    with api.step.nest('install packages'):
      flags = InstallPackagesRequest.Flags(
          compile_source=False, use_goma=api.cros_sdk.has_goma_config())
      response = api.cros_build_api.SysrootService.InstallPackages(
          InstallPackagesRequest(sysroot=sysroot, flags=flags,
                                 packages=packages, chroot=api.cros_sdk.chroot,
                                 use_flags=build_config.build.use_flags))
      api.cros_bisect.set_compile_failures(response.failed_packages)
      api.failures.raise_failed_packages(response.failed_packages)
    if api.cros_infra_config.should_exit(install_packages):
      return

  version = api.cros_version.read_workspace_version()
  api.easy.set_property_step('chromeos_version', str(version))

  image_types = build_config.build.image_types
  if image_types:
    with api.step.nest('build images'):
      response = api.cros_build_api.ImageService.Create(
          CreateImageRequest(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              image_types=image_types,
              builder_path=api.cros_artifacts.artifacts_gs_path(
                  build_target, build_config.id.type)), timeout=45 * 60)
      api.failures.raise_failed_packages(response.failed_packages)
    with api.step.nest('test images'):
      failed_images = []
      # For now, as in legacy CQ, we only test base images.
      for image in [i for i in response.images if i.type == BASE]:
        result_dir = api.path.mkdtemp(prefix="image-test-result-")
        if not api.cros_build_api.ImageService.Test(
            TestImageRequest(
                image=image, build_target=build_target,
                result=TestImageRequest.Result(directory=str(result_dir)),
                chroot=api.cros_sdk.chroot)).success:
          failed_images.append(image)
      api.failures.raise_failed_image_tests(failed_images)

  ebuilds_run_spec = build_config.unit_tests.ebuilds_run_spec
  if api.cros_infra_config.should_run(ebuilds_run_spec):
    with api.step.nest('run ebuild tests'):
      flags = BuildTargetUnitTestRequest.Flags(
          empty_sysroot=build_config.unit_tests.empty_sysroot)
      response = api.cros_build_api.TestService.BuildTargetUnitTest(
          BuildTargetUnitTestRequest(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              result_path=str(api.path.mkdtemp()),
              package_blacklist=build_config.unit_tests.package_blacklist,
              flags=flags), timeout=2 * 60 * 60)
      api.failures.raise_failed_packages(response.failed_packages)
    if api.cros_infra_config.should_exit(ebuilds_run_spec):
      return

  artifact_types = build_config.artifacts.artifact_types
  if artifact_types:
    api.cros_artifacts.upload_artifacts(
        build_target, build_config.id.type,
        build_config.artifacts.artifacts_gs_bucket, artifact_types)

  prebuilts = build_config.artifacts.prebuilts
  if prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
    api.cros_prebuilts.upload_target_prebuilts(
        build_target, build_config.id.type,
        build_config.artifacts.prebuilts_gs_bucket,
        private=(prebuilts == BuilderConfig.Artifacts.PRIVATE))

def get_packages(api, build_config):
  """Returns the packages that should be built for this invocation.

  Returns the list of packages that should be built for this or an
  empty list if all packages should be built. This will be a subset
  for cases like FindIt bisection where only prior failed packages
  are attempted or special builders like kernel builders.

  Args:
    api (RecipeApi): See RunSteps.
    build_config (BuilderConfig): builder configuration for the builder

  Returns:
    list[PackageInfo] of packages to build
  """
  return api.cros_bisect.get_packages() or build_config.build.packages

def get_target_versions(api, build_target):
  """Returns 'target_versions' in dict form.

  Returns the 'target_versions' values for this build in a dict form
  suitable for output as a build property. Note that this cannot be
  called until after the creation of the sysroot is finished.

  Args:
    api (RecipeApi): See RunSteps.
    build_target (chromiumos.BuildTarget): The BuildTarget being built.

  Returns:
    dict of target versions
  """
  response = api.cros_build_api.PackageService.GetTargetVersions(
      GetTargetVersionsRequest(
          chroot=api.cros_sdk.chroot,
          build_target=build_target))
  return json_pb.MessageToDict(response)

def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(change=1234),
      common_pb2.GerritChange(change=2341),
  ]

  def cq_build_with_gerrit_change(builder='amd64-generic-cq'):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder=builder)
    build.input.gerrit_changes.extend(mock_CLs)
    return api.buildbucket.build(build)

  yield (api.test('basic') +  #
         cq_build_with_gerrit_change() +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('no-needs-chrome') +  #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'call chromite.api.PackageService/BuildsChrome.read output file',
             api.file.read_raw(content='{"builds_chrome": false}')) +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('no-has-chrome-prebuilt') +  #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'call chromite.api.PackageService/HasChromePrebuilt'
             '.read output file',
             api.file.read_raw(content='{"has_prebuilt": false}')) +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('with-findit-bisect') +  #
         cq_build_with_gerrit_change() +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') + api.properties(
                 **{
                     'build_target': {
                         'name': 'amd64-generic'
                     },
                     '$chromeos/cros_bisect':
                         CrosBisectProperties(compile={'targets': [
                             api.cros_bisect.serialized_package_info(
                                 'foo', 'cat1', '1'),
                             api.cros_bisect.serialized_package_info(
                                 'bar', 'cat1', '2'),
                             api.cros_bisect.serialized_package_info(
                                 'baz', 'cat2', '3'),
                         ]})
                 }))

  yield (
      api.test('with-gerrit-changes') +  #
      api.cros_relevance.simulate_run_pointless_build_checker(
          name='post-sync pointless build check') + api.buildbucket.try_build(
              project='chromeos', bucket='cq', builder='amd64-generic-cq') +  #
      api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-exit-install-packages') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-bisect') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('fail-image-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'amd64-generic'}) +  #
         api.step_data(
             'test images.call chromite.api.ImageService/Test.read output file',
             api.file.read_raw(content='{"success": false}')))

  yield (api.test('no-run-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='grunt-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'grunt'}))

  yield (api.test('run-exit-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='grunt-unittest-only-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'grunt'}))

  yield (api.test('pointless-build-check') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check', build_is_pointless=True) +
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('with-builder-config-limited-packages') +  #
         api.buildbucket.try_build(
             project='chromeos', bucket='cq',
             builder='arm-generic-v42-buildtest-postsubmit') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='post-sync pointless build check') +  #
         api.properties(build_target={'name': 'arm-generic'}))

  yield (
      api.test('initsdk-destroy-chroot-tests') +  #
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq') +  #
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1))

  yield (
      api.test('updatesdk-destroy-chroot-tests') +  #
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq') +  #
      api.step_data(
          'update sdk.call chromite.api.SdkService/Update.call build API script',
          retcode=1))

  yield (
      api.test('destroy-chroot-failed-step-tests') +  #
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq') +  #
      api.step_data(
          'post-sync pointless build check.call chromite.api.DependencyService/'
          'GetBuildDependencyGraph.write input file', retcode=1))

  yield (api.test('builder-no-longer-exists') +  #
         cq_build_with_gerrit_change('no-exist-builder'))
