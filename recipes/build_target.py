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
]

import hashlib

from google.protobuf import json_format as json_pb

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import BASE
from PB.chromiumos.common import PrepareForBuildResponse
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import TestImageRequest
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.packages import UprevPackagesRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
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


def RunSteps(api, properties):
  build_target = properties.build_target
  force_relevant_build = properties.force_relevant_build
  gitiles_commit = api.buildbucket.gitiles_commit
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  with api.step.nest('read builder config') as step:
    try:
      build_config = api.cros_infra_config.get_builder_config(
          api.buildbucket.build.builder.builder)
    except LookupError:
      step.presentation.step_text = 'config not found, assuming deleted'
      return
    step.presentation.logs['builder config'] = [str(build_config)]
    api.easy.set_property_step('builder_config',
                               json_pb.MessageToDict(build_config))
    parent_tag = [x.value
                  for x in api.buildbucket.build.tags
                  if x.key == 'parent_buildbucket_id']
    if parent_tag:
      step.presentation.links['orchestrator link'] = (
          'https://ci.chromium.org/b/%s' % parent_tag[0])

  api.cros_bisect.set_bisect_builder(build_target.name)
  api.cros_sdk.set_use_flags(build_config.build.use_flags)

  with api.cros_source.checkout_overlays_context(), \
      api.cros_sdk.cleanup_context(
          checkout_path=api.cros_source.workspace_path), \
      api.context(cwd=api.cros_source.workspace_path):
    DoRunSteps(api, build_target, build_config, gitiles_commit, gerrit_changes,
               force_relevant_build)


def DoRunSteps(api, build_target, build_config, gitiles_commit, gerrit_changes,
               force_relevant_build):
  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  api.cros_source.sync_snapshot(gitiles_commit)

  # Define a function to append the failure step with the failed packages
  def _failed_pkg_names(output_proto):
    # sort package names, join them with ',', and limit to 50 chars.
    failed_packages = ','.join(sorted([p.package_name for p
                                        in output_proto.failed_packages]))

    # Add to the default response step name like: ": package1,package2"
    # If it's extremely long add elipsis and a fancy sha to make unique.
    if len(failed_packages) > 50:
      fp_sha = hashlib.sha256()
      fp_sha.update(failed_packages)
      failed_packages = (failed_packages[:50] +
                          ('...(%s)' % fp_sha.hexdigest()[0:4]))
    if failed_packages:
      failed_packages = ': ' + failed_packages
    return failed_packages

  patch_sets = []
  if gerrit_changes and build_config.build.apply_gerrit_changes:
    with api.step.nest('cherry-pick gerrit changes'):
      patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes,
                                               include_files=True)
      api.cros_source.apply_gerrit_patch_sets(patch_sets)

  # Prepare for the build.  If the build is pointless, we are done.
  artifacts = build_config.artifacts
  relevance = PrepareForBuildResponse.UNKNOWN
  if artifacts.artifact_types:
    relevance = api.cros_artifacts.prepare_for_build(
        artifacts.artifact_types, None, None, artifacts.input_artifacts)
    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # PrepareForBuild endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no PrepareForBuild endpoint
    # defined, then the result will be UNKNOWN.
    if (not force_relevant_build and
        relevance == PrepareForBuildResponse.POINTLESS):
      return

  with api.step.nest('uprev packages') as step:
    request = UprevPackagesRequest(
        chroot=api.cros_sdk.chroot,
        build_targets=[BuildTarget(name=build_target.name)],
        overlay_type=OVERLAYTYPE_BOTH)
    response = api.cros_build_api.PackageService.Uprev(request)

  with api.step.nest('init sdk') as step:
    api.cros_sdk.build_chmod_chroot()
    # If build config has sdk_cache_version present, toggle no_replace flag in
    # build api call based on if there is a mismatch between config value and
    # what is present on disk. In short: replace existing sdk cache if mismatch.
    no_replace_flag = True
    if build_config.general.sdk_cache_version:
      step.presentation.logs['sdk cache version'] = [
          'Version in config: %s' % build_config.general.sdk_cache_version,
          'Version on disk: %s' % api.cros_sdk.sdk_cache_version,
      ]
      no_replace_flag = (str(build_config.general.sdk_cache_version) ==
                         str(api.cros_sdk.sdk_cache_version))
    response = api.cros_build_api.SdkService.Create(
        CreateSdkRequest(
            flags=CreateSdkRequest.Flags(
                no_replace=no_replace_flag,
                # Test mounting the SDK as an image only in staging for now.
                no_use_image=(build_config.general.environment !=
                              BuilderConfig.General.STAGING)),
            chroot=api.cros_sdk.chroot))
    step.presentation.logs['sdk version'] = [str(response.version.version)]
    if build_config.general.sdk_cache_version:
      api.cros_sdk.sdk_cache_version = build_config.general.sdk_cache_version
    api.cros_sdk.link_chroot(api.cros_source.workspace_path)

  with api.step.nest('detect toolchain change') as step:
    toolchain_changed = api.cros_relevance.check_for_toolchain_change(
        gerrit_changes, gitiles_commit, chroot=api.cros_sdk.chroot)
    if toolchain_changed:
      api.cros_sdk.mark_sdk_as_dirty()
      step.presentation.step_text = ('change detected')
      api.easy.set_property_step('testing_toolchain', True)
    else:
      step.presentation.step_text = ('no change')
      api.easy.set_property_step('testing_toolchain', False)

  with api.step.nest('update sdk'):
    flags = UpdateSdkRequest.Flags(
        build_source=build_config.build.sdk_update.compile_source,
        toolchain_changed=toolchain_changed)
    api.cros_build_api.SdkService.Update(
        UpdateSdkRequest(chroot=api.cros_sdk.chroot,
                         toolchain_targets=[build_target],
                         flags=flags))

  with api.step.nest('create sysroot'):
    profile = None
    if build_config.build.portage_profile.profile:
      profile = Profile(name=build_config.build.portage_profile.profile)
    create_sysroot_response = api.cros_build_api.SysrootService.Create(
        SysrootCreateRequest(
            build_target=build_target, profile=profile,
            chroot=api.cros_sdk.chroot, flags=SysrootCreateRequest.Flags(
                chroot_current=True, replace=True,
                toolchain_changed=toolchain_changed)))
    sysroot = create_sysroot_response.sysroot

  packages = get_packages(api, build_config)
  target_graph, sdk_graph = api.cros_relevance.get_dependency_graph(
      build_target=build_target, chroot=api.cros_sdk.chroot, packages=packages)

  if (not force_relevant_build and not toolchain_changed and
      relevance != PrepareForBuildResponse.NEEDED and
      api.cros_relevance.is_build_pointless(
          gerrit_changes,
          gitiles_commit,
          dep_graph=target_graph,
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
        compile_source=build_config.build.install_toolchain.compile_source,
        toolchain_changed=toolchain_changed)
    response = api.cros_build_api.SysrootService.InstallToolchain(
        InstallToolchainRequest(sysroot=sysroot, chroot=api.cros_sdk.chroot,
                                flags=flags), response_lambda=_failed_pkg_names)
    api.failures.set_failed_packages(install_tc_step, response.failed_packages)

  install_packages = build_config.build.install_packages
  if api.cros_infra_config.should_run(install_packages.run_spec):
    # Long chain of |= to determine if chrome requires rebuild.
    chrome_source_build = toolchain_changed
    chrome_source_build |= api.chrome.builds_chrome_from_source(
        build_target=build_target, chroot=api.cros_sdk.chroot,
        packages=packages,
        ignore_prebuilts=install_packages.compile_source)
    chrome_source_build |= api.chrome.diffed_files_requires_rebuild(
        patch_sets=patch_sets)

    if chrome_source_build:
      chrome_root = api.path['start_dir'].join('chrome')
      api.chrome.sync(chrome_root, api.cros_sdk.chroot, build_target,
                      build_config.chrome.internal)
      api.cros_sdk.set_chrome_root(str(chrome_root))
      api.cros_sdk.set_goma_config(
          str(api.goma.goma_dir), str(api.goma.goma_client_json),
          api.goma.goma_approach,
          str(api.path.mkdtemp(prefix='goma-logs-')),
          'stats.binaryproto', 'counterz.binaryproto')

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
            artifacts.input_artifacts, name='prepare artifacts final')
      flags = InstallPackagesRequest.Flags(
          compile_source=install_packages.compile_source,
          use_goma=(not install_packages.disable_goma and
                    api.cros_sdk.has_goma_config()),
          toolchain_changed=toolchain_changed)

      install_pkg_request = InstallPackagesRequest(
          sysroot=sysroot, flags=flags,
          packages=packages, chroot=api.cros_sdk.chroot,
          use_flags=build_config.build.use_flags,
          goma_config=api.cros_sdk.goma_config())
      response = api.cros_build_api.SysrootService.InstallPackages(
          install_pkg_request, response_lambda=_failed_pkg_names)

      # Process goma response to upload logs, stats, and counterz.
      api.goma.process_artifacts(response,
                                 install_pkg_request.goma_config.log_dir.dir,
                                 build_target.name)

      api.cros_bisect.set_compile_failures(response.failed_packages)
      api.failures.set_failed_packages(ip_step, response.failed_packages)
    if api.cros_infra_config.should_exit(install_packages.run_spec):
      return

  version = api.cros_version.read_workspace_version()
  api.easy.set_property_step('chromeos_version', str(version))

  image_types = build_config.build.build_images.image_types
  if image_types:
    with api.step.nest('build images') as bi_step:
      response = api.cros_build_api.ImageService.Create(
          CreateImageRequest(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              image_types=image_types,
              builder_path=api.cros_artifacts.artifacts_gs_path(
                  build_target, build_config.id.type)), timeout=45 * 60,
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
          continue # pragma: no cover

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
    with api.step.nest('run ebuild tests') as reb_step:
      flags = BuildTargetUnitTestRequest.Flags(
          empty_sysroot=build_config.unit_tests.empty_sysroot)
      response = api.cros_build_api.TestService.BuildTargetUnitTest(
          BuildTargetUnitTestRequest(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              result_path=str(api.path.mkdtemp()),
              package_blacklist=build_config.unit_tests.package_blacklist,
              flags=flags), timeout=2 * 60 * 60,
              response_lambda=_failed_pkg_names)
      api.failures.set_failed_packages(reb_step, response.failed_packages)
    if api.cros_infra_config.should_exit(ebuilds_run_spec):
      return

  if artifacts.artifact_types:
    api.cros_artifacts.upload_artifacts(
        build_target, build_config.id.type,
        artifacts.artifacts_gs_bucket, artifacts.artifact_types,
        sysroot=sysroot, chroot=api.cros_sdk.chroot,
        publish_info=artifacts.publish_artifacts)

  prebuilts = artifacts.prebuilts
  if prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
    api.cros_prebuilts.upload_target_prebuilts(
        build_target, build_config.id.type,
        build_config.artifacts.prebuilts_gs_bucket,
        private=(prebuilts == BuilderConfig.Artifacts.PRIVATE))

  with api.step.nest('validate SDK reuse'):
    if api.cros_relevance.is_depgraph_affected(gerrit_changes, gitiles_commit,
                                               dep_graph=sdk_graph):
      api.cros_sdk.mark_sdk_as_dirty()


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
  return (api.cros_bisect.get_packages() or
          build_config.build.install_packages.packages)


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
    return api.buildbucket.build(build) + no_toolchain_change()

  def toolchain_build(builder='orderfile-generate-toolchain'):
    """Generate a test build proto."""
    build = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain', builder=builder,
        tags=[{'key': 'parent_buildbucket_id', 'value': 'parent_id'}])
    return api.buildbucket.build(build)

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
        'detect toolchain change.path relevancy check.read output file',
        api.file.read_raw(content=serialized))

  def force_toolchain_change():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = False
    serialized = resp.SerializeToString()
    return api.step_data(
        'detect toolchain change.path relevancy check.read output file',
        api.file.read_raw(content=serialized))

  yield (api.test('basic') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('forced') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        force_relevant_build=True))

  yield (api.test('forced-pointless') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'},
                        force_relevant_build=True))

  yield (api.test('with-goma-props') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(build_target={'name': 'amd64-generic'}) +  #
         api.properties(**{'$chromeos/goma': GomaProperties(
             client_version='staging',
             goma_approach=common.GomaConfig.RBE_PROD,
         )}))

  yield (api.test('no-needs-chrome') +  #
         cq_build_with_gerrit_change() +  #
         make_build_not_pointless() +  #
         api.step_data(
             'call chromite.api.PackageService/BuildsChrome.read output file',
             api.file.read_raw(content='{"builds_chrome": false}')) +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('no-has-chrome-prebuilt') +  #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'call chromite.api.PackageService/HasChromePrebuilt'
             '.read output file',
             api.file.read_raw(content='{"has_prebuilt": false}')) +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('fails_install_with_many_packages') +  #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(
               content='''{
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

  yield (api.test('install_package_no_goma') + #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(
               content='''{
               "events": [
                {
                  "name": "fake_package-path/fake-package-name-0.0.1-r2",
                  "durationMilliseconds": "1523",
                  "timestampMilliseconds": "1580481610805"
                }]
               }''')))

  yield (api.test('install_package_with_goma') + #
         cq_build_with_gerrit_change() +  #
         api.step_data(
             'install packages'
             '.call chromite.api.SysrootService/InstallPackages'
             '.read output file',
             api.file.read_raw(
               content='''{
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

  yield (api.test('prepare-for-build') + #
         toolchain_build() + #
         api.step_data(
             'prepare artifacts.call chromite.api.ToolchainService/'
             'PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield (api.test('prepare-for-build-late-pointless') + #
         toolchain_build() + #
         api.step_data(
             'install packages.prepare artifacts final.call chromite.api.'
             'ToolchainService/PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield (api.test('prepare-for-build-verify') + #
         toolchain_build(builder='orderfile-verify-toolchain') + #
         api.step_data(
             'prepare artifacts.call chromite.api.ToolchainService/'
             'PrepareForBuild.read output file',
             api.file.read_raw(content='{"build_relevance": "NEEDED"}')))

  yield (api.test('compile-update-sdk') + #
         toolchain_build(builder='atlas-llvm-next'))

  yield (api.test('with-findit-bisect') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(
             **{
                 'build_target': {
                     'name': 'amd64-generic'
                 },
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

  yield (api.test('with-custom-snapshot') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(
             **{
                 'build_target': {
                     'name': 'amd64-generic'
                 },
                 '$chromeos/cros_source':
                     CrosSourceProperties(
                         snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                             isolated_hash='foohash',
                             isolate_server='server.com'
                         ),
                     )
             }))

  yield (api.test('with-custom-DEPS') +  #
         cq_build_with_gerrit_change() +  #
         api.properties(
             **{
                 'build_target': {
                     'name': 'amd64-generic'
                 },
                 '$chromeos/chrome':
                     ChromeProperties(
                         deps_isolate=ChromeProperties.DepsIsolate(
                             isolated_hash='moohash',
                             isolate_server='cows.com'
                         ),
                     )
             }))

  yield (api.test('with-gerrit-changes') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(build_target={'name': 'amd64-generic'}))

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
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         no_toolchain_change() +  #
         make_build_pointless() +  #
         api.properties(build_target={'name': 'amd64-generic'}))

  yield (api.test('toolchain-change-test') +  #
         cq_build_with_gerrit_change() +  #
         force_toolchain_change())

  yield (api.test('with-builder-config-limited-packages') +  #
         api.buildbucket.try_build(
             project='chromeos', bucket='cq',
             builder='arm-generic-v42-buildtest-postsubmit') +  #
         api.properties(build_target={'name': 'arm-generic'}))

  yield (api.test('initsdk-existing-sdk-cache') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "2"}')))

  yield (api.test('initsdk-existing-outdated-sdk-cache') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "1"}')))

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
          'update sdk.call chromite.api.SdkService/'
          'Update.call build API script', retcode=1))

  yield (api.test('destroy-chroot-failed-step-tests') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='amd64-generic-cq') +  #
         api.step_data(
             'dependency graph calculation.call chromite.api.DependencyService/'
             'GetBuildDependencyGraph.write input file', retcode=1))

  yield (api.test('builder-no-longer-exists'))
