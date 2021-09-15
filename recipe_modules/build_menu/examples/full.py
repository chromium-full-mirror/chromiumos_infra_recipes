# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'cros_bisect',
    'cros_build_api',
    'test_util',
]

from recipe_engine import post_process

from PB.chromiumos import common
from PB.recipe_modules.chromeos.build_menu.examples.full import FullProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

PROPERTIES = FullProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder(
      missing_ok=properties.missing_config_ok) as config:
    api.assertions.assertEqual(config, api.build_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      api.assertions.assertIsNotNone(api.build_menu.config_or_default)
      return
    return DoRunSteps(api, properties)


def DoRunSteps(api, properties):
  with api.build_menu.setup_workspace_and_chroot() as relevant:
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        not properties.no_sysroot)
    if properties.forced_relevant:
      api.assertions.assertTrue(relevant)

    if properties.no_sysroot:
      api.assertions.assertIsNone(api.build_menu.sysroot)
    else:
      api.build_menu.bootstrap_sysroot()
      api.build_menu.install_packages()
      api.build_menu.build_and_test_images()
      api.build_menu.build_and_test_images(include_version=True)
      if properties.upload_prebuilts:
        api.build_menu.upload_prebuilts()
      api.build_menu.upload_artifacts()

    # Sometimes these are RepeatedCompositeFieldContainter, sometimes they are
    # list.  Cast them.
    api.assertions.assertEqual(
        list(env_info.packages), list(properties.expected_packages))


def GenTests(api):
  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      cq=True,
  )

  # Slim CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'slim-cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'), cq=True,
      build_target='atlas-slim')

  # This covers the env_info.pointless check.
  yield api.build_menu.test(
      'pointless-cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'), cq=True,
      pointless=True)

  # Release build.
  yield api.build_menu.test(
      'release-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='cloudready-release-R90-13816.B')),
      build_target='cloudready-release-R90-13816.B', bucket='release')

  # Run the other tests that we only run in the module.
  yield api.build_menu.test(
      'postsubmit-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/BuildSetup',
                                          '{"build_relevance": "UNKNOWN"}'),
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)),
      input_properties={'$chromeos/build_menu': dict(artifact_build=True)})

  yield api.build_menu.test(
      'toolchain-cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.build_menu.set_toolchain_cls_return(True), cq=True)

  yield api.build_menu.test(
      'has-no-artifacts',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      build_target='arm-generic')

  yield api.build_menu.test(
      'postsubmit-with-changes',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusFailure),
      api.post_check(post_process.DoesNotRun, 'cherry-pick gerrit changes'),
      build_target='arm-generic', cq=True, bucket='postsubmit')

  yield api.build_menu.test(
      'postsubmit-with-snapshot-prebuilts',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)),
      input_properties={
          '$chromeos/build_menu':
              dict(artifact_build=True),
          '$chromeos/cros_prebuilts':
              dict(enable_snapshot_prebuilts=True, send_snapshot_prebuilts=1)
      })

  for forced in False, True:
    yield api.build_menu.test(
        ('forced-' if forced else '') + 'pointless-artifact-build',
        api.swarming.properties(
            bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
        api.properties(
            FullProperties(
                build_target=common.BuildTarget(name='chell'),
                artifact_build=True, forced_relevant=forced, expected_packages=[
                    common.PackageInfo(category='chromeos-base',
                                       package_name='chromeos-chrome')
                ])), build_target='chell', bucket='toolchain',
        builder='orderfile-generate-toolchain', artifact_pointless=True,
        input_properties={
            '$chromeos/build_menu':
                dict(artifact_build=True, force_relevant_build=forced)
        })

  yield api.build_menu.test(
      'no-sysroot',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(FullProperties(no_sysroot=True)))

  yield api.build_menu.test(
      'no-config',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      builder='no-config')

  yield api.build_menu.test(
      'with-findit-bisect',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
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
          }), bucket='bisect')

  yield api.build_menu.test(
      'missing-ok-config',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          FullProperties(missing_config_ok=True, expect_missing_config=True)),
      builder='no-config')

  yield api.build_menu.test(
      'code-coverage-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      builder='sarien-code-coverage-postsubmit', build_target='sarien',
      input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True)
      })

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-format',
    api.swarming.properties(
        bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
    api.properties(
      **api.test_util.build_menu_properties(
        container_version_format=\
        '{staging?}{build-target}-cq.{unknown-field}'
      )
    ),
    api.expect_exception('RuntimeError'),
    api.post_check(post_process.StatusException),
    api.post_check(
      post_process.ResultReasonRE,
      'Unknown fields found in version format string',
    ),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-characters',
    api.swarming.properties(
        bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq/{cros-version}'
      )
    ),
    api.expect_exception('RuntimeError'),
    api.post_check(post_process.StatusException),
    api.post_check(
      post_process.ResultReasonRE,
      'Invalid tag format',
    ),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-len',
    api.swarming.properties(
        bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
    api.properties(
      **api.test_util.build_menu_properties(
        container_version_format=\
        256*'a'
      )
    ),
    api.expect_exception('RuntimeError'),
    api.post_check(post_process.StatusException),
    api.post_check(
      post_process.ResultReasonRE,
      'Tag is too long',
    ),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'no-container-endpoint',
    api.swarming.properties(
        bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    api.cros_build_api.remove_endpoints(
      ['TestService/BuildTestServiceContainers']
    ),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'container-build-error',
    api.swarming.properties(
        bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),

    # Simulate a failure building a single container
    api.cros_build_api.set_api_return(
      'build and upload test service containers',
      endpoint='TestService/BuildTestServiceContainers',
      data='{ "results": [ { "failure" : {} } ]}',
    ),
    cq=True,
  )
