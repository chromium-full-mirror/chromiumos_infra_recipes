# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'test_util',
]

from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromiumos import common
from PB.recipe_modules.chromeos.build_menu.examples.full import FullProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse

PROPERTIES = FullProperties


def RunSteps(api, properties):
  build_target = properties.build_target or common.BuildTarget(name='eve')

  with api.build_menu.configure_builder(
      build_target, missing_ok=properties.missing_config_ok) as config:
    api.assertions.assertEqual(config, api.build_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      api.assertions.assertIsNotNone(api.build_menu.config_or_default)
      return

    relevance = api.build_menu.setup_workspace_and_chroot(
        properties.artifact_build, properties.forced_relevant)
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        not properties.no_sysroot)
    if properties.forced_relevant:
      api.assertions.assertEqual(relevance, Relevance.NEEDED)

    if properties.no_sysroot:
      api.assertions.assertIsNone(api.build_menu.sysroot)
    else:
      api.build_menu.bootstrap_sysroot_and_install_packages()
      api.build_menu.build_and_test_images()
      api.build_menu.upload_artifacts()
      if properties.upload_prebuilts:
        api.build_menu.upload_prebuilts()

    api.assertions.assertEqual(env_info.packages, properties.expected_packages)


def GenTests(api):

  yield api.test(
      'postsubmit-build',
      api.test_util.test_child_build('amd64-generic').build,
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)))

  yield api.test('cq-build',
                 api.test_util.test_child_build('amd64-generic', cq=True).build)

  yield api.test('toolchain-cq-build',
                 api.test_util.test_child_build('amd64-generic', cq=True).build,
                 api.build_menu.set_toolchain_cls_return(True))

  yield api.test('pointless-cq-build',
                 api.test_util.test_child_build('amd64-generic', cq=True).build,
                 api.build_menu.set_pointless_return(True))

  yield api.test(
      'forced-pointless-artifact-build',
      api.test_util.test_child_build(
          'amd64-generic', bucket='toolchain',
          builder='orderfile-generate-toolchain').build,
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/PrepareForBuild',
                                          '{"build_relevance": "POINTLESS"}'),
      api.properties(
          FullProperties(
              build_target=common.BuildTarget(name='chell'),
              artifact_build=True, forced_relevant=True, expected_packages=[
                  common.PackageInfo(category='chromeos-base',
                                     package_name='chromeos-chrome')
              ])))

  yield api.test(
      'pointless-artifact-build',
      api.test_util.test_child_build(
          'amd64-generic', bucket='toolchain',
          builder='orderfile-generate-toolchain').build,
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/PrepareForBuild',
                                          '{"build_relevance": "POINTLESS"}'),
      api.properties(
          FullProperties(
              build_target=common.BuildTarget(name='chell'),
              artifact_build=True, expected_packages=[
                  common.PackageInfo(category='chromeos-base',
                                     package_name='chromeos-chrome')
              ])))

  yield api.test('no-sysroot',
                 api.test_util.test_child_build(
                     'amd64-generic',
                 ).build, api.properties(FullProperties(no_sysroot=True)))

  yield api.test(
      'no-config',
      api.test_util.test_child_build('no-config', builder='no-config').build)

  yield api.test(
      'missing-ok-config',
      api.test_util.test_child_build('amd64-generic',
                                     builder='no-config').build,
      api.properties(
          FullProperties(missing_config_ok=True, expect_missing_config=True)))
