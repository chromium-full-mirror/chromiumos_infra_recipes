# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'cros_bisect',
    'test_util',
]

from PB.chromiumos import common
from PB.recipe_modules.chromeos.build_menu.examples.full import FullProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

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

    relevant = api.build_menu.setup_workspace_and_chroot(
        properties.artifact_build, properties.forced_relevant)
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        not properties.no_sysroot)
    if properties.forced_relevant:
      api.assertions.assertTrue(relevant)

    if properties.no_sysroot:
      api.assertions.assertIsNone(api.build_menu.sysroot)
    else:
      api.build_menu.bootstrap_sysroot_and_install_packages()
      api.build_menu.build_and_test_images()
      if properties.upload_prebuilts:
        api.build_menu.upload_prebuilts()
      api.build_menu.upload_artifacts()

    # Sometimes these are RepeatedCompositeFieldContainter, sometimes they are
    # list.  Cast them.
    api.assertions.assertEqual(
        list(env_info.packages), list(properties.expected_packages))


def GenTests(api):

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test('cq-build', cq=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test('pointless-cq-build', cq=True, pointless=True)

  # Run the other tests that we only run in the module.
  yield api.build_menu.test(
      'postsubmit-build',
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)))

  yield api.build_menu.test('toolchain-cq-build',
                            api.build_menu.set_toolchain_cls_return(True),
                            cq=True)

  for forced in False, True:
    yield api.build_menu.test(
        ('forced-' if forced else '') + 'pointless-artifact-build',
        api.properties(
            FullProperties(
                build_target=common.BuildTarget(name='chell'),
                artifact_build=True, forced_relevant=forced, expected_packages=[
                    common.PackageInfo(category='chromeos-base',
                                       package_name='chromeos-chrome')
                ])), bucket='toolchain', builder='orderfile-generate-toolchain',
        artifact_pointless=True)

  yield api.build_menu.test('no-sysroot',
                            api.properties(FullProperties(no_sysroot=True)))

  yield api.build_menu.test('no-config', builder='no-config')

  yield api.build_menu.test(
      'with-findit-bisect',
      api.properties(
          FullProperties(expected_packages=[
              common.PackageInfo(category='cat1', package_name='foo',
                                 version='1'),
              common.PackageInfo(category='cat1', package_name='bar',
                                 version='2'),
              common.PackageInfo(category='cat2', package_name='baz',
                                 version='3')
          ])),
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

  yield api.build_menu.test(
      'missing-ok-config',
      api.properties(
          FullProperties(missing_config_ok=True, expect_missing_config=True)),
      builder='no-config')
