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
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_cost',
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
    'sysroot_util',
    'workspace_util',
]

import hashlib

from google.protobuf import json_format as json_pb

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import BASE
from PB.chromiumos.common import PrepareForBuildResponse as Relevance
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import TestImageRequest
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse

from PB.recipe_modules.chromeos.goma.goma import GomaProperties

PROPERTIES = BuildTargetProperties

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]

# All step timeouts are in seconds.
STEP_TIMEOUTS = {
    'uprev': 10 * 60,
    'create_sdk': 40 * 60,
    'update_sdk': 60 * 60,
    'create_sysroot': 10 * 60,
    'install_toolchain': 30 * 60,
    'install_packages': 8 * 60 * 60,
    'build_image': 45 * 60,
    'unit_tests': 2 * 60 * 60,
}


def RunSteps(api, properties):
  build_target = properties.build_target
  force_relevant_build = properties.force_relevant_build

  config = api.cros_infra_config.configure_builder(
      api.buildbucket.gitiles_commit,
      api.buildbucket.build.input.gerrit_changes)
  if not config:
    # No config found, already logged.
    return

  api.cros_bisect.set_bisect_builder(build_target.name)
  api.cros_sdk.set_use_flags(config.build.use_flags)
  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    DoRunSteps(api, build_target, config, api.cros_infra_config.gitiles_commit,
               api.cros_infra_config.gerrit_changes, force_relevant_build)


def DoRunSteps(api, build_target, config, gitiles_commit, gerrit_changes,
               force_relevant_build):
  is_staging = config.general.environment == BuilderConfig.General.STAGING
  # Toolchain builders compile many large packages from source and need higher
  # step timeouts to successfully complete.
  long_timeouts = config.id.type == BuilderConfig.Id.TOOLCHAIN

  # Set up source checkouts.
  api.workspace_util.sync_to_commit(staging=is_staging)
  # Apply any appropriate gerrit_changes.
  api.workspace_util.apply_changes()

  # Early check to see if the build is pointless. (No chroot nor sysroot yet.)
  artifacts = config.artifacts
  relevance = api.sysroot_util.update_for_artifact_build(
      None, config.artifacts, config.build.prepare_for_build.additional_args,
      force_relevance=force_relevant_build)
  if relevance == Relevance.POINTLESS:
    return

  api.cros_sdk.create_chroot(
      version=config.general.sdk_cache_version, use_image=is_staging,
      timeout_sec=None if long_timeouts else STEP_TIMEOUTS['create_sdk'])
  api.cros_sdk.uprev_packages(
      build_targets=[BuildTarget(name=build_target.name)])

  toolchain_changed = api.cros_sdk.update_chroot(
      gitiles_commit, gerrit_changes, toolchain_targets=[build_target],
      build_source=config.build.sdk_update.compile_source)
  long_timeouts |= toolchain_changed

  with api.step.nest('create sysroot'):
    profile = None
    if config.build.portage_profile.profile:
      profile = Profile(name=config.build.portage_profile.profile)
    create_sysroot_response = api.cros_build_api.SysrootService.Create(
        SysrootCreateRequest(
            build_target=build_target, profile=profile,
            chroot=api.cros_sdk.chroot, flags=SysrootCreateRequest.Flags(
                chroot_current=True, replace=True,
                toolchain_changed=toolchain_changed)),
        timeout=(STEP_TIMEOUTS['create_sysroot']
                 if not long_timeouts else None))
    sysroot = create_sysroot_response.sysroot

  packages = get_packages(api, config)
  dep_graph = api.cros_relevance.get_dependency_graph(
      build_target=build_target, chroot=api.cros_sdk.chroot, packages=packages)

  if (not force_relevant_build and not toolchain_changed and
      relevance != Relevance.NEEDED and api.cros_relevance.is_build_pointless(
          gerrit_changes,
          gitiles_commit,
          dep_graph=dep_graph.target,
      )):
    # TODO: When it becomes possible to add tags from the build itself set:
    # "hide-in-gerrit": "pointless"
    # See https://crrev.com/c/1913895.
    return

  try:
    api.easy.set_property_step('target_versions',
                               get_target_versions(api, build_target))
  except:  # pragma: no cover # pylint: disable=bare-except
    # Failing on kernel buildtest builders, see https://crbug.com/1017583.
    pass

  with api.step.nest('install toolchain') as install_tc_step:
    flags = InstallToolchainRequest.Flags(
        compile_source=config.build.install_toolchain.compile_source,
        toolchain_changed=toolchain_changed)
    response = api.cros_build_api.SysrootService.InstallToolchain(
        InstallToolchainRequest(sysroot=sysroot, chroot=api.cros_sdk.chroot,
                                flags=flags), response_lambda=_failed_pkg_names,
        timeout=(STEP_TIMEOUTS['install_toolchain']
                 if not long_timeouts else None))
    api.failures.set_failed_packages(install_tc_step, response.failed_packages)

  install_packages = config.build.install_packages
  chrome_source_needed = False
  if api.cros_infra_config.should_run(install_packages.run_spec):
    with api.step.nest('check chrome source needed') as cs_pres:
      needs_chrome = api.chrome.needs_chrome(build_target=build_target,
                                            chroot=api.cros_sdk.chroot,
                                            packages=packages)
      if needs_chrome:
        # Only bother to do these checks if the build target needs chrome src.
        needs_built = not api.chrome.has_chrome_prebuilt(
            build_target=build_target, chroot=api.cros_sdk.chroot,
            ignore_prebuilts=install_packages.compile_source)
        files_changed = api.chrome.diffed_files_requires_rebuild(
            patch_sets=api.workspace_util.patch_sets)

        # TODO(crbug.com/1063327): Remove dep_graph access and corresponding
        # use, we shouldn't be inspecting this, rather, call the build api.
        # I don't bother breaking this out into a function lest someone use it.
        flattened_packages = []
        for package in dep_graph[0].package_deps:  # dep_graph[0]==target deps.
          for dep_package in package.dependency_packages:
            flattened_packages.append(dep_package)

        follower_needs_chrome = api.chrome.follower_needs_chrome(
            build_target=build_target,
            chroot=api.cros_sdk.chroot,
            packages=flattened_packages)

        # Evaluate the |or| of the reasons we might want local chrome source.
        chrome_source_needed = (toolchain_changed or
                              needs_built or
                              files_changed or
                              follower_needs_chrome)
      cs_pres.step_text = str(chrome_source_needed)

      if chrome_source_needed:
        chrome_root = api.path['start_dir'].join('chrome')
        api.chrome.sync(chrome_root, api.cros_sdk.chroot, build_target,
                        config.chrome.internal)
        api.cros_sdk.set_chrome_root(str(chrome_root))
        api.cros_sdk.set_goma_config(
            str(api.goma.goma_dir),
            str(api.goma.goma_client_json), api.goma.goma_approach,
            str(api.path.mkdtemp(prefix='goma-logs-')), 'stats.binaryproto',
            'counterz.binaryproto')

    with api.step.nest('install packages') as ip_step:
      if artifacts.artifact_types:
        # Final round of preparation to build artifacts.  Some artifacts need
        # to use portage to fully prepare, so they have to finish preparation
        # inside the SDK.
        #
        # We don't care what the return value is, since we're committed to
        # running at least install packages at this point.
        api.cros_artifacts.prepare_for_build(
            artifacts.artifact_types, api.cros_sdk.chroot, sysroot,
            artifacts.input_artifacts,
            additional_args=config.build.prepare_for_build.additional_args,
            name='prepare artifacts final')
      flags = InstallPackagesRequest.Flags(
          compile_source=install_packages.compile_source,
          use_goma=(not install_packages.disable_goma and
                    api.cros_sdk.has_goma_config()),
          toolchain_changed=toolchain_changed)

      install_pkg_request = InstallPackagesRequest(
          sysroot=sysroot, flags=flags, packages=packages,
          chroot=api.cros_sdk.chroot, use_flags=config.build.use_flags,
          goma_config=api.cros_sdk.goma_config())
      response = api.cros_build_api.SysrootService.InstallPackages(
          install_pkg_request, response_lambda=_failed_pkg_names,
          timeout=(STEP_TIMEOUTS['install_packages']
                    if not long_timeouts else None))

      # Process goma response to upload logs, stats, and counterz.
      api.goma.process_artifacts(response,
                                  install_pkg_request.goma_config.log_dir.dir,
                                  build_target.name, is_staging)

      step_name = ('install packages|'
                    'call chromite.api.SysrootService/InstallPackages|'
                    '{}'.format(
                        api.cros_build_api.response_step_name(
                            response, _failed_pkg_names)))

      api.cros_bisect.set_compile_failures(response.failed_packages, step_name,
                                            config.general.critical.value)
      api.failures.set_failed_packages(ip_step, response.failed_packages)
    if api.cros_infra_config.should_exit(install_packages.run_spec):
      return

  version = api.cros_version.read_workspace_version()
  api.easy.set_property_step('chromeos_version', str(version))

  image_types = config.build.build_images.image_types
  if image_types:
    with api.step.nest('build images') as bi_step:
      response = api.cros_build_api.ImageService.Create(
          CreateImageRequest(
              build_target=build_target,
              chroot=api.cros_sdk.chroot,
              image_types=image_types,
              builder_path=api.cros_artifacts.artifacts_gs_path(
                  config.id.name, build_target, config.id.type),
          ), timeout=STEP_TIMEOUTS['build_image'],
          response_lambda=_failed_pkg_names)
      api.failures.set_failed_packages(bi_step, response.failed_packages)
    with api.step.nest('test images'):
      failed_images = []

      # For now, as in legacy CQ, we only test base images. Images created as a
      # sideeffect (not explicitly requested in image_types) are not tested.
      for image in response.images:
        if image.type != BASE or image.type not in image_types:
          # This continue statement is not correctly caught by coveragepy:
          # https://bitbucket.org/ned/coveragepy/issues/198/continue-marked-as-not-covered
          continue  # pragma: no cover

        result_dir = api.path.mkdtemp(prefix='image-test-result-')
        if not api.cros_build_api.ImageService.Test(
            TestImageRequest(
                image=image, build_target=build_target,
                result=TestImageRequest.Result(directory=str(result_dir)),
                chroot=api.cros_sdk.chroot)).success:
          failed_images.append(image)
      api.failures.raise_failed_image_tests(failed_images)

  ebuilds_run_spec = config.unit_tests.ebuilds_run_spec
  if api.cros_infra_config.should_run(ebuilds_run_spec):
    with api.step.nest('run ebuild tests') as reb_step:
      flags = BuildTargetUnitTestRequest.Flags(
          empty_sysroot=config.unit_tests.empty_sysroot)
      response = api.cros_build_api.TestService.BuildTargetUnitTest(
          BuildTargetUnitTestRequest(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              result_path=str(api.path.mkdtemp()),
              package_blacklist=config.unit_tests.package_blacklist,
              flags=flags), timeout=STEP_TIMEOUTS['unit_tests'],
          response_lambda=_failed_pkg_names)
      api.failures.set_failed_packages(reb_step, response.failed_packages)
    if api.cros_infra_config.should_exit(ebuilds_run_spec):
      return

  if artifacts.artifact_types:
    api.cros_artifacts.upload_artifacts(
        config.id.name, build_target, config.id.type,
        artifacts.artifacts_gs_bucket, artifacts.artifact_types,
        sysroot=sysroot, chroot=api.cros_sdk.chroot,
        publish_info=artifacts.publish_artifacts,
        additional_args=config.build.prepare_for_build.additional_args)

  prebuilts = artifacts.prebuilts
  if prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
    api.cros_prebuilts.upload_target_prebuilts(
        build_target, config.id.type, config.artifacts.prebuilts_gs_bucket,
        private=(prebuilts == BuilderConfig.Artifacts.PRIVATE))

  with api.step.nest('validate SDK reuse'):
    if api.cros_relevance.is_depgraph_affected(gerrit_changes, gitiles_commit,
                                               dep_graph=dep_graph.sdk):
      api.cros_sdk.mark_sdk_as_dirty()

  api.easy.set_property_step(
      'build_cost',
      api.bot_cost.calculate_build_cost(api.buildbucket.build.id, 'large'))


def get_packages(api, config):
  """Returns the packages that should be built for this invocation.

  Returns the list of packages that should be built for this or an
  empty list if all packages should be built. This will be a subset
  for cases like FindIt bisection where only prior failed packages
  are attempted or special builders like kernel builders.

  Args:
    api (RecipeApi): See RunSteps.
    config (BuilderConfig): builder configuration for the builder

  Returns:
    list[PackageInfo] of packages to build
  """
  return (api.cros_bisect.get_packages() or
          config.build.install_packages.packages)


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
      GetTargetVersionsRequest(chroot=api.cros_sdk.chroot,
                               build_target=build_target))
  return json_pb.MessageToDict(response)


# Define a function to append the failure step with the failed packages
def _failed_pkg_names(output_proto):
  # sort package names, join them with ',', and limit to 50 chars.
  failed_packages = ','.join(
      sorted(p.package_name for p in output_proto.failed_packages))

  # Add to the default response step name like: ": package1,package2"
  # If it's extremely long add elipsis and a fancy sha to make unique.
  if len(failed_packages) > 50:
    fp_sha = hashlib.sha256()
    fp_sha.update(failed_packages)
    failed_packages = (
        failed_packages[:50] + ('...(%s)' % fp_sha.hexdigest()[0:4]))
  if failed_packages:
    failed_packages = ': ' + failed_packages
  return failed_packages


def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(change=1234),
      common_pb2.GerritChange(change=2341),
  ]

  def cq_build(builder='amd64-generic-cq', build_target='amd64-generic',
               gerrit_changes=True, no_toolchain=True):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder=builder)
    if gerrit_changes:
      build.input.gerrit_changes.extend(mock_CLs)
    ret = api.buildbucket.build(build)
    if no_toolchain:
      ret += no_toolchain_change()
    if build_target:
      ret += api.properties(build_target={'name': build_target})
    return ret

  def cq_build_no_changes(builder='amd64-generic-cq',
                          build_target='amd64-generic'):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder=builder)
    ret = api.buildbucket.build(build)
    if build_target:
      ret += api.properties(build_target={'name': build_target})
    return ret

  def toolchain_build(builder='orderfile-generate-toolchain',
                      build_target='eve'):
    """Generate a test build proto."""
    build = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain', builder=builder, tags=[{
            'key': 'parent_buildbucket_id',
            'value': 'parent_id'
        }])
    ret = api.buildbucket.build(build)
    if build_target:
      ret += api.properties(build_target={'name': build_target})
    return ret

  def make_build_pointless():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = True
    serialized = resp.SerializeToString()
    return api.step_data(
        'pointless build check.depgraph relevance check.read output file',
        api.file.read_raw(content=serialized))

  def make_build_not_pointless():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = False
    serialized = resp.SerializeToString()
    return api.step_data(
        'pointless build check.depgraph relevance check.read output file',
        api.file.read_raw(content=serialized))

  def no_toolchain_change():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = True
    serialized = resp.SerializeToString()
    return api.step_data(
        'update sdk.detect toolchain change.path relevancy check.'
        'read output file', api.file.read_raw(content=serialized))

  def force_toolchain_change():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = False
    serialized = resp.SerializeToString()
    return api.step_data(
        'update sdk.detect toolchain change.path relevancy check.'
        'read output file', api.file.read_raw(content=serialized))

  yield (api.test('basic') +  #
         cq_build(build_target=None) +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('forced') +  #
         cq_build(build_target=None) +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        force_relevant_build=True))

  yield (api.test('forced-pointless') +  #
         cq_build(builder='amd64-generic-cq', build_target=None) +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        force_relevant_build=True))

  yield (api.test('with-goma-props') +  #
         cq_build(build_target=None) +  #
         api.properties(build_target={'name': 'amd64-generic'}) +  #
         api.properties(
             **{
                 '$chromeos/goma':
                     GomaProperties(
                         client_version='staging',
                         goma_approach=common.GomaConfig.RBE_PROD,
                     )
             }))

  yield (api.test('no-needs-chrome') +  #
         cq_build() +  #
         make_build_not_pointless() +  #
         api.step_data(
             'check chrome source needed.'
             'call chromite.api.PackageService/BuildsChrome.read output file',
             api.file.read_raw(content='{"builds_chrome": false}')))

  yield (api.test('no-has-chrome-prebuilt') +  #
         cq_build() +  #
         api.step_data(
             'check chrome source needed.'
             'call chromite.api.PackageService/HasChromePrebuilt'
             '.read output file',
             api.file.read_raw(content='{"has_prebuilt": false}')))

  yield (api.test('fails_install_with_many_packages') +  #
         cq_build() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(content='''{
                            "failedPackages": [{
                              "category": "chromeos-base",
                              "packageName": "thislongpackagenameomg",
                              "version": "0.0.1-r199"
                            }, {
                              "category": "safari-base",
                              "packageName": "thisisanexceedinglylongpackage",
                              "version": "0.0.1-r129"
                            }, {
                              "category": "edge-base",
                              "packageName": "shortpackagename",
                              "version": "0.0.1-r197"
                            }]
                          }''')))

  yield (api.test('install_package_no_goma') +  #
         cq_build() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(content='''{
               "events": [
                {
                  "name": "fake_package-path/fake-package-name-0.0.1-r2",
                  "durationMilliseconds": "1523",
                  "timestampMilliseconds": "1580481610805"
                }]
               }''')))

  yield (api.test('install_package_with_goma') +  #
         cq_build() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(content='''{
               "gomaArtifacts": {
                 "counterzFile": "counterz.binaryproto",
                 "statsFile": "stats.binaryproto",
                 "logFiles": [
                   "compiler_proxy-subproc.chromeos-ci.log.INFO.20200131.84.gz",
                   "compiler_proxy.chromeos-ci.log.INFO.20200131-063322.81.gz",
                   "gomacc.chromeos-ci.log.INFO.20200131-073921.1717.tar.gz",
                   "ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005.8.gz"
                 ]
               },
               "events": [
               {
                 "name": "fake_package-path/fake-package-name-0.0.1-r2",
                 "durationMilliseconds": "1523",
                 "timestampMilliseconds": "1580481610805"
               }]
             }''')))

  yield (api.test('prepare-for-build') +  #
         toolchain_build() +  #
         api.step_data(
             'prepare artifacts.call chromite.api.ToolchainService/'
             'PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield (api.test('prepare-for-build-late-pointless') +  #
         toolchain_build() +  #
         api.step_data(
             'install packages.prepare artifacts final.call chromite.api.'
             'ToolchainService/PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield (api.test('prepare-for-build-verify') +  #
         toolchain_build(builder='orderfile-verify-toolchain') +  #
         api.step_data(
             'prepare artifacts.call chromite.api.ToolchainService/'
             'PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "NEEDED"}')))

  yield (api.test('compile-update-sdk') +  #
         toolchain_build(builder='atlas-llvm-next', build_target='atlas'))

  yield (api.test('with-findit-bisect') +  #
         cq_build() +  #
         api.properties(
             **{
                 '$chromeos/cros_bisect':
                     CrosBisectProperties(
                         compile={
                             'targets': [
                                 api.cros_bisect.serialized_package_info(
                                     'foo', 'cat1', '1'),
                                 api.cros_bisect.serialized_package_info(
                                     'bar', 'cat1', '2'),
                                 api.cros_bisect.serialized_package_info(
                                     'baz', 'cat2', '3'),
                             ]
                         })
             }))

  yield (
      api.test('with-custom-snapshot') +  #
      cq_build() +  #
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                          isolated_hash='foohash', isolate_server='server.com'),
                  )
          }))

  yield (
      api.test('with-custom-DEPS') +  #
      cq_build() +  #
      api.properties(
          **{
              '$chromeos/chrome':
                  ChromeProperties(
                      version='2.0',
                      deps_isolate=ChromeProperties.DepsIsolate(
                          isolated_hash='moohash', isolate_server='cows.com'),
                  )
          }))

  yield (api.test('with-gerrit-changes') +  #
         cq_build())

  yield (api.test('run-exit-install-packages') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-bisect') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('run-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('fail-image-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit') +  #
         api.properties(build_target={'name': 'amd64-generic'}) +  #
         api.step_data(
             'test images.call chromite.api.ImageService/Test.read output file',
             api.file.read_raw(content='{"success": false}')))

  yield (api.test('no-run-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='grunt-postsubmit') +  #
         api.properties(build_target={'name': 'grunt'}))

  yield (api.test('run-exit-ebuild-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='grunt-unittest-only-postsubmit') +  #
         api.properties(build_target={'name': 'grunt'}))

  yield (api.test('pointless-build-check') +  #
         cq_build() +  #
         make_build_pointless())

  yield (api.test('toolchain-change-test') +  #
         cq_build() +  #
         force_toolchain_change())

  yield (api.test('with-builder-config-limited-packages') +  #
         cq_build(builder='orderfile-verify-toolchain',
                  build_target='arm-generic'))

  yield (api.test('initsdk-existing-sdk-cache') +  #
         cq_build_no_changes(builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "2"}')))

  yield (api.test('initsdk-existing-outdated-sdk-cache') +  #
         cq_build_no_changes(builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "1"}')))

  yield (
      api.test('initsdk-destroy-chroot-tests') +  #
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq') +  #
      api.properties(build_target={'name': 'amd64-generic'}) +  #
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1))

  yield (api.test('updatesdk-destroy-chroot-tests') +  #
         cq_build_no_changes(builder='amd64-generic-cq') +  #
         api.step_data(
             'update sdk.call chromite.api.SdkService/'
             'Update.call build API script', retcode=1))

  yield (api.test('destroy-chroot-failed-step-tests') +  #
         cq_build_no_changes(builder='amd64-generic-cq') +  #
         api.step_data(
             'dependency graph calculation.call chromite.api.DependencyService/'
             'GetBuildDependencyGraph.write input file', retcode=1))

  yield api.test('builder-no-longer-exists')
