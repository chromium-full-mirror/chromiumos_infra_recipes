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
    'build_menu',
    'cros_artifacts',
    'cros_bisect',
    'cros_infra_config',
    'sysroot_util',
    'workspace_util',
]

import json

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse

from PB.recipe_modules.chromeos.goma.goma import GomaProperties

PROPERTIES = BuildTargetProperties

UPLOADABLE_PREBUILTS_CONFIGS = [
    BuilderConfig.Artifacts.PUBLIC, BuilderConfig.Artifacts.PRIVATE
]


def RunSteps(api, properties):
  build_target = properties.build_target
  with api.build_menu.configure_builder(build_target) as config:
    if config:
      DoRunSteps(api, config, build_target, properties)


def DoRunSteps(api, config, build_target, properties):
  # TODO(crbug/1053703): artifact_build is something that we can remove when we
  # split up build_target.py into individual builders, since we will know
  # whether it is True or False based on what recipe we are.
  artifact_build = api.cros_artifacts.has_output_artifacts(
      config.artifacts.artifacts_info)

  if api.build_menu.setup_workspace_and_chroot(
      artifact_build=artifact_build,
      forced_relevant=properties.force_relevant_build) == Relevance.POINTLESS:
    return

  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return
  packages = env_info.packages

  # TODO(crbug/1053703): All of the following if statements should be removed as
  # we break build_target.py into the various builders.
  install_packages = config.build.install_packages
  if api.cros_infra_config.should_run(install_packages.run_spec):
    api.build_menu.bootstrap_sysroot_and_install_packages(
        config, packages, artifact_build=artifact_build)
    if api.cros_infra_config.should_exit(install_packages.run_spec):
      return

  ebuilds_run_spec = config.unit_tests.ebuilds_run_spec
  api.build_menu.build_and_test_images(
      config=config,
      run_tests=api.cros_infra_config.should_run(ebuilds_run_spec))
  if api.cros_infra_config.should_exit(ebuilds_run_spec):
    return

  if artifact_build:
    api.build_menu.upload_artifacts(config)

  if config.artifacts.prebuilts in UPLOADABLE_PREBUILTS_CONFIGS:
    api.build_menu.upload_prebuilts(config)


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
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'forced',
      cq_build(build_target=None),
      api.properties(build_target={'name': 'amd64-generic'},
                     force_relevant_build=True),
  )

  yield api.test(
      'forced-pointless',
      cq_build(builder='amd64-generic-cq', build_target=None),
      api.properties(build_target={'name': 'amd64-generic'},
                     force_relevant_build=True),
  )

  yield api.test(
      'with-goma-props',
      cq_build(build_target=None),
      api.properties(build_target={'name': 'amd64-generic'}),
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
      api.step_data(
          'install packages.check chrome source needed.'
          'call chromite.api.PackageService/NeedsChromeSource.read output file',
          api.file.read_raw(content='{"needs_chrome_source": false}')),
  )

  yield api.test(
      'fails_install_with_many_packages',
      cq_build(),
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
      api.step_data(
          'install packages'
          '.call chromite.api.SysrootService/InstallPackages'
          '.read output file',
          api.file.read_raw(content=json.dumps(goma_artifacts))),
  )

  yield api.test(
      'prepare-for-build',
      toolchain_build(),
      api.step_data(
          'prepare artifacts.call chromite.api.ArtifactsService/'
          'PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "POINTLESS"}')),
  )

  yield api.test(
      'with-findit-bisect',
      cq_build(),
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

  yield api.test('with-gerrit-changes', cq_build())

  yield api.test(
      'run-exit-install-packages',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-bisect'),
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'run-ebuild-tests',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-postsubmit'),
      api.properties(build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'fail-image-tests',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='amd64-generic-postsubmit'),
      api.properties(build_target={'name': 'amd64-generic'}),
      api.step_data(
          'build images.test images.call chromite.api.ImageService/Test.read output file',
          api.file.read_raw(content='{"success": false}')),
  )

  yield api.test(
      'no-run-ebuild-tests',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='grunt-postsubmit'),
      api.properties(build_target={'name': 'grunt'}),
  )

  yield api.test(
      'run-exit-ebuild-tests',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='grunt-unittest-only-postsubmit'),
      api.properties(build_target={'name': 'grunt'}),
  )

  yield api.test('pointless-build-check', cq_build(), make_build_pointless())

  yield api.test('toolchain-change-test', cq_build(), force_toolchain_change())

  yield api.test(
      'with-builder-config-limited-packages',
      cq_build(builder='orderfile-verify-toolchain',
               build_target='arm-generic'))

  yield api.test('builder-no-longer-exists')
