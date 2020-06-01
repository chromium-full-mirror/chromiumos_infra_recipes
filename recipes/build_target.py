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
    'metadata_json',
    'sysroot_util',
    'workspace_util',
]

import hashlib
import json

from google.protobuf import json_format as json_pb

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromite.api.packages import GetTargetVersionsRequest
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

# All step timeouts are in seconds.  All are moving to modules.
STEP_TIMEOUTS = {
    'install_packages': 8 * 60 * 60,
    'build_image': 45 * 60,
    'unit_tests': 2 * 60 * 60,
}


def RunSteps(api, properties):
  build_target = properties.build_target

  with api.bot_cost.build_cost_context():
    config = api.cros_infra_config.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)
    if not config:
      # No config found, already logged.
      return

    api.cros_bisect.set_bisect_builder(build_target.name)
    api.cros_sdk.set_use_flags(config.build.use_flags)
    with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context(), \
        api.metadata_json.context(config, build_target):
      DoRunSteps(api, config, build_target, properties)


def DoRunSteps(api, config, build_target, properties):
  # Short versions of several variables that may have been altered in RunSteps.
  gitiles_commit = api.cros_infra_config.gitiles_commit
  gerrit_changes = api.cros_infra_config.gerrit_changes
  forced_relevant = properties.force_relevant_build

  is_staging = config.general.environment == BuilderConfig.General.STAGING

  # Set up source checkouts.
  api.workspace_util.sync_to_commit(staging=is_staging)
  # Apply any appropriate gerrit_changes.
  api.workspace_util.apply_changes()

  # Early check to see if the build is pointless. (No chroot nor sysroot yet.)
  relevance = api.sysroot_util.update_for_artifact_build(
      None, config.artifacts, force_relevance=forced_relevant)
  if relevance == Relevance.POINTLESS:
    return
  # Remember if the the artifact build says it's NEEDED.
  forced_relevant = forced_relevant or relevance == Relevance.NEEDED

  api.cros_sdk.uprev_packages(build_targets=[build_target])
  api.cros_sdk.create_chroot(
      version=config.general.sdk_cache_version, use_image=is_staging,
      timeout_sec=None if config.build.sdk_update.compile_source else 'DEFAULT')

  api.cros_sdk.update_chroot(
      gitiles_commit, gerrit_changes, toolchain_targets=[build_target],
      build_source=config.build.sdk_update.compile_source)

  sysroot = api.sysroot_util.create_sysroot(
      build_target, config.build.portage_profile.profile)

  packages = get_packages(api, config)
  # Note: the dependency graph requires a sysroot prior to crrev.com/c/2197226.
  # TODO(crbug/1053703): After 2020-11-12, if there is no sysroot, that's ok.
  dep_graph = api.cros_relevance.get_dependency_graph(
      sysroot=sysroot, chroot=api.cros_sdk.chroot, packages=packages)

  with api.step.nest('validate SDK reuse'):
    # If any of the changes affect the sdk, mark the sdk as dirty.
    if api.cros_relevance.is_depgraph_affected(gerrit_changes, gitiles_commit,
                                               dep_graph=dep_graph.sdk):
      api.cros_sdk.mark_sdk_as_dirty()

  # In the cases where force_relevant is True:
  # 1. input_properties.force_relevant_build is True, and/or
  # 2. output_properties.testing_toolchain is True (now tracked in
  #    cros_relevance), and/or
  # 3. output_properties.artifact_prep is True.
  if api.cros_relevance.is_build_pointless(gerrit_changes, gitiles_commit,
                                           dep_graph=dep_graph.target,
                                           force_relevant=forced_relevant):
    # TODO: When it becomes possible to add tags from the build itself set:
    # "hide-in-gerrit": "pointless"
    # See https://crrev.com/c/1913895.
    return

  target_versions = get_target_versions(api, build_target)
  api.easy.set_property_step('target_versions', target_versions)
  try:
    if api.cros_artifacts.has_output_artifacts(config.artifacts.artifacts_info):
      api.metadata_json.add_version_entries(target_versions)
      api.metadata_json.upload_to_gs(config, build_target, partial=True)
  except:  # pragma: no cover # pylint: disable=bare-except
    pass

  api.sysroot_util.bootstrap_sysroot(
      compile_source=config.build.install_toolchain.compile_source)

  install_packages = config.build.install_packages

  def _InstallPackagesRequest():
    """Helper to make InstallPackagesRequest."""
    return InstallPackagesRequest(
        chroot=api.cros_sdk.chroot, sysroot=sysroot, packages=packages,
        flags=InstallPackagesRequest.Flags(
            compile_source=install_packages.compile_source,
            use_goma=api.cros_sdk.has_goma_config(),
            toolchain_changed=api.workspace_util.toolchain_cls_applied),
        use_flags=config.build.use_flags,
        goma_config=api.cros_sdk.goma_config())

  with api.step.nest('check chrome source needed') as cs_pres:
    if api.chrome.needs_chrome_source(_InstallPackagesRequest(), dep_graph,
                                      cs_pres):
      # This will change the return from _InstallPackagesRequest().
      chrome_root = api.path['start_dir'].join('chrome')
      api.chrome.sync(chrome_root, api.cros_sdk.chroot, build_target,
                      config.chrome.internal)
      if not install_packages.disable_goma:
        api.cros_sdk.configure_goma(chrome_root)

  if api.cros_infra_config.should_run(install_packages.run_spec):
    with api.step.nest('install packages') as ip_step:
      # Final round of preparation to build artifacts.  Some artifacts need
      # to use portage (or a chroot and/or sysroot) in order to fully prepare,
      # so they have to finish preparation inside the SDK.
      #
      # We don't care what the return value is, since we're committed to
      # running at least install packages at this point.  Let the module know
      # that we are forcing relevance.
      api.sysroot_util.update_for_artifact_build(api.cros_sdk.chroot,
                                                 config.artifacts,
                                                 force_relevance=True,
                                                 name='prepare artifacts final')
      install_pkg_request = _InstallPackagesRequest()
      response = api.cros_build_api.SysrootService.InstallPackages(
          install_pkg_request,
          response_lambda=api.cros_build_api.failed_pkg_names,
          timeout=(STEP_TIMEOUTS['install_packages']
                   if not api.cros_sdk.long_timeouts else None))

      # Process goma response to upload logs, stats, and counterz.
      api.goma.process_artifacts(response,
                                 install_pkg_request.goma_config.log_dir.dir,
                                 build_target.name, is_staging)

      step_name = ('install packages|'
                   'call chromite.api.SysrootService/InstallPackages|'
                   '{}'.format(
                       api.cros_build_api.response_step_name(
                           response, api.cros_build_api.failed_pkg_names)))

      api.cros_bisect.set_compile_failures(response.failed_packages, step_name,
                                           config.general.critical.value)
      api.failures.set_failed_packages(ip_step, response.failed_packages)
    if api.cros_infra_config.should_exit(install_packages.run_spec):
      return

  version = api.cros_version.read_workspace_version()
  api.easy.set_property_step('chromeos_version', str(version))
  disable_rootfs_verification = config.build.build_images.disable_rootfs_verification
  disk_layout = config.build.build_images.disk_layout
  image_types = config.build.build_images.image_types

  builder_path = api.cros_artifacts.artifacts_gs_path(config.id.name,
                                                      build_target,
                                                      config.id.type)

  api.sysroot_util.build_images(image_types, builder_path,
                                disable_rootfs_verification, disk_layout)

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
          response_lambda=api.cros_build_api.failed_pkg_names)
      api.failures.set_failed_packages(reb_step, response.failed_packages)
    if api.cros_infra_config.should_exit(ebuilds_run_spec):
      return

  if api.cros_artifacts.has_output_artifacts(config.artifacts.artifacts_info):
    api.cros_artifacts.upload_artifacts(
        config.id.name, build_target, config.id.type,
        config.artifacts.artifacts_gs_bucket, sysroot=sysroot,
        chroot=api.cros_sdk.chroot,
        artifacts_info=config.artifacts.artifacts_info)

  if config.artifacts.prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
    api.cros_prebuilts.upload_target_prebuilts(
        build_target, config.id.type, config.artifacts.prebuilts_gs_bucket,
        private=(config.artifacts.prebuilts == BuilderConfig.Artifacts.PRIVATE))


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


def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(change=1234),
      common_pb2.GerritChange(change=2341),
  ]
  # A fake build to satisfy metadata logic.
  md_build = api.buildbucket.try_build_message(bucket='cq',
                                               builder='amd64-generic-cq')

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
    build_msg = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain', builder=builder, tags=[{
            'key': 'parent_buildbucket_id',
            'value': 'parent_id'
        }])
    ret = api.buildbucket.build(build_msg)
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
        'init sdk.detect toolchain change.path relevancy check.'
        'read output file', api.file.read_raw(content=serialized))

  def force_toolchain_change():
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = False
    serialized = resp.SerializeToString()
    return api.step_data(
        'init sdk.detect toolchain change.path relevancy check.'
        'read output file', api.file.read_raw(content=serialized))

  yield api.test(
      'basic',
      cq_build(build_target=None),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'forced',
      cq_build(build_target=None),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(build_target={'name': 'amd64-generic'},
                     force_relevant_build=True),
  )

  yield api.test(
      'forced-pointless',
      cq_build(builder='amd64-generic-cq', build_target=None),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(build_target={'name': 'amd64-generic'},
                     force_relevant_build=True),
  )

  yield api.test(
      'with-goma-props',
      cq_build(build_target=None),
      api.properties(build_target={'name': 'amd64-generic'}),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      client_version='staging',
                      goma_approach=common.GomaConfig.RBE_PROD,
                  )
          }),
  )

  yield api.test(
      'no-needs-chrome',
      cq_build(),
      make_build_not_pointless(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'check chrome source needed.'
          'call chromite.api.PackageService/NeedsChromeSource.read output file',
          api.file.read_raw(content='{"needs_chrome_source": false}')),
  )

  yield api.test(
      'fails_install_with_many_packages',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'install packages'
          '.call chromite.api.SysrootService/InstallPackages'
          '.read output file',
          api.file.read_raw(
              content=json.dumps(
                  dict(
                      failedPackages=[{
                          "category": "chromeos-base",
                          "packageName": "thislongpackagenameomg",
                          "version": "0.0.1-r199",
                      }, {
                          "category": "safari-base",
                          "packageName": "thisisanexceedinglylongpackage",
                          "version": "0.0.1-r129",
                      }, {
                          "category": "edge-base",
                          "packageName": "shortpackagename",
                          "version": "0.0.1-r197",
                      }],
                  )))),
  )

  yield api.test(
      'install_package_no_goma',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'install packages'
          '.call chromite.api.SysrootService/InstallPackages'
          '.read output file',
          api.file.read_raw(
              content=json.dumps(
                  dict(
                      events=[{
                          "name":
                              "fake_package-path/fake-package-name-0.0.1-r2",
                          "durationMilliseconds":
                              "1523",
                          "timestampMilliseconds":
                              "1580481610805"
                      }],
                  )))),
  )

  goma_artifacts = dict(
      gomaArtifacts={
          "counterzFile":
              "counterz.binaryproto",
          "statsFile":
              "stats.binaryproto",
          "logFiles": [
              "compiler_proxy-subproc.chromeos-ci.log.INFO.20200131"
              ".84.gz", "compiler_proxy.chromeos-ci.log.INFO.20200131-063322"
              ".81.gz", "gomacc.chromeos-ci.log.INFO.20200131-073921.1717"
              ".tar.gz", "ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005"
              ".8.gz"
          ]
      },
      events=[{
          "name": "fake_package-path/fake-package-name-0.0.1-r2",
          "durationMilliseconds": "1523",
          "timestampMilliseconds": "1580481610805"
      }],
  )
  yield api.test(
      'install_package_with_goma',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'install packages'
          '.call chromite.api.SysrootService/InstallPackages'
          '.read output file',
          api.file.read_raw(content=json.dumps(goma_artifacts))),
  )

  yield api.test(
      'prepare-for-build',
      toolchain_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'prepare artifacts.call chromite.api.ArtifactsService/'
          'PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "POINTLESS"}')),
  )

  yield api.test(
      'prepare-for-build-late-pointless',
      toolchain_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'install packages.prepare artifacts final.call chromite.api.'
          'ArtifactsService/PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "POINTLESS"}')),
  )

  yield api.test(
      'prepare-for-build-verify',
      toolchain_build(builder='orderfile-verify-toolchain'),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'prepare artifacts.call chromite.api.ArtifactsService/'
          'PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "NEEDED"}')),
  )

  yield api.test(
      'compile-update-sdk',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      toolchain_build(builder='atlas-llvm-next', build_target='atlas'),
  )

  yield api.test(
      'with-findit-bisect',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
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
          }),
  )

  yield api.test(
      'with-custom-snapshot',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                          isolated_hash='foohash', isolate_server='server.com'),
                  )
          }),
  )

  yield api.test(
      'with-custom-DEPS',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.properties(
          **{
              '$chromeos/chrome':
                  ChromeProperties(
                      version='2.0',
                      deps_isolate=ChromeProperties.DepsIsolate(
                          isolated_hash='moohash', isolate_server='cows.com'),
                  )
          }),
  )

  yield api.test(
      'with-gerrit-changes',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      cq_build(),
  )

  yield api.test(
      'run-exit-install-packages',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-bisect'),
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'run-ebuild-tests',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-postsubmit'),
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'fail-image-tests',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-postsubmit'),
      api.properties(build_target={'name': 'amd64-generic'}),
      api.step_data(
          'build images.test images.call chromite.api.ImageService/Test.read output file',
          api.file.read_raw(content='{"success": false}')),
  )

  yield api.test(
      'no-run-ebuild-tests',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='grunt-postsubmit'),
      api.properties(build_target={'name': 'grunt'}),
  )

  yield api.test(
      'run-exit-ebuild-tests',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='grunt-unittest-only-postsubmit'),
      api.properties(build_target={'name': 'grunt'}),
  )

  yield api.test(
      'pointless-build-check',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      make_build_pointless(),
  )

  yield api.test(
      'toolchain-change-test',
      cq_build(),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      force_toolchain_change(),
  )

  yield api.test(
      'with-builder-config-limited-packages',
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      cq_build(builder='orderfile-verify-toolchain',
               build_target='arm-generic'),
  )

  yield api.test(
      'initsdk-existing-sdk-cache',
      cq_build_no_changes(builder='staging-amd64-generic-cq'),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data('init sdk.read sdk cache version json',
                    api.raw_io.output_text('{"version": "2"}')),
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.read output file',
          api.file.read_raw(content='{"version": {"version": 2}}')),
  )

  yield api.test(
      'initsdk-existing-outdated-sdk-cache',
      cq_build_no_changes(builder='staging-amd64-generic-cq'),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data('init sdk.read sdk cache version json',
                    api.raw_io.output_text('{"version": "1"}')),
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.read output file',
          api.file.read_raw(content='{"version": {"version": 2}}')),
  )

  yield api.test(
      'initsdk-destroy-chroot-tests',
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq'),
      api.properties(build_target={'name': 'amd64-generic'}),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1),
  )

  yield api.test(
      'updatesdk-destroy-chroot-tests',
      cq_build_no_changes(builder='amd64-generic-cq'),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'update sdk.call chromite.api.SdkService/'
          'Update.call build API script', retcode=1),
  )

  yield api.test(
      'destroy-chroot-failed-step-tests',
      cq_build_no_changes(builder='amd64-generic-cq'),
      api.buildbucket.simulated_get(md_build, 'metadata setup.buildbucket.get'),
      api.step_data(
          'dependency graph calculation.call chromite.api.DependencyService/'
          'GetBuildDependencyGraph.write input file', retcode=1),
  )

  yield api.test('builder-no-longer-exists')
