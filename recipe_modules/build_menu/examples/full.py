# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'recipe_engine/step',
    'build_menu',
    'cros_bisect',
    'cros_build_api',
    'cros_history',
    'test_util',
]

from recipe_engine import post_process

from PB.chromiumos import common
from PB.recipe_modules.chromeos.build_menu.examples.full import FullProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

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
  cherry_pick_changes = not properties.dont_cherry_pick_changes
  with api.build_menu.setup_workspace_and_chroot(
      cherry_pick_changes=cherry_pick_changes):
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        not properties.no_sysroot)
    api.build_menu.is_cq_build_relevant()
    # pylint: disable=protected-access
    api.assertions.assertEqual(properties.forced_relevant,
                               api.build_menu._force_relevant_build)

    if properties.no_sysroot:
      api.assertions.assertIsNone(api.build_menu.sysroot)
    else:
      api.build_menu.bootstrap_sysroot()
      api.build_menu.install_packages()
      api.build_menu.build_and_test_images()
      api.build_menu.build_and_test_images(
          include_version=True,
          builder_path_template='{target}-release/{version}')
      if properties.upload_prebuilts:
        api.build_menu.upload_prebuilts()
      api.build_menu.upload_artifacts()
      api.build_menu.create_containers()
      api.build_menu.add_child_build_ids_to_output_property()

    # Sometimes these are RepeatedCompositeFieldContainter, sometimes they are
    # list.  Cast them.
    api.assertions.assertEqual(
        list(env_info.packages), list(properties.expected_packages))


def GenTests(api):

  def get_buildbucket_simulated_search_results(builder):
    """
    Get buildbucket simulated search results for finding child builders.

    Args:
      builder (str): Builder name.

    Returns:
      (TestData): Test data for 'buildbucket.search' step.
    """
    return api.buildbucket.simulated_search_results([
        build_pb2.Build(id=101, builder={'builder': builder}),
        build_pb2.Build(id=102, builder={'builder': builder})
    ])

  def check_child_build_output_properties(check, steps,
                                          expect_child_builds=False):
    """
    Validation of child build ids in build output properties.
    """
    child_builds = post_process.GetBuildProperties(steps).get('child_builds')
    if child_builds:
      check(
          expect_child_builds and len(child_builds) == 2 and
          child_builds[0] == '101' and child_builds[1] == '102')
    else:
      check(not expect_child_builds)

  # Build with parallelization experiment.
  # TODO(b/216849056): Remove test case once fully enabled.
  yield api.test(
      'parallel-experiment',
      api.buildbucket.ci_build(
          builder='atlas-cq', experiments=[
              'chromeos.cros_infra_config.image_builder_parallelization'
          ]),
      # Simulate a failure running unit tests
      api.cros_build_api.set_api_return(
          'run ebuild tests', endpoint='TestService/BuildTargetUnitTest',
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ),
  )

  yield api.build_menu.test(
      'cq-build',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      get_buildbucket_simulated_search_results('atlas'),
      api.post_check(post_process.StatusSuccess),
      api.post_check(lambda check, steps: check_child_build_output_properties(check, steps, True)),
      cq=True,
  )

  yield api.build_menu.test(
    'cq-build-no-cherry-pick',
      api.properties(FullProperties(dont_cherry_pick_changes=True)),
    api.properties(
        **api.test_util.build_menu_properties(
          build_target_name='atlas',
          container_version_format=\
            '{staging?}{build-target}-cq.{cros-version}-{bbid}'
        )
    ),
    get_buildbucket_simulated_search_results('atlas'),
    api.post_check(post_process.StatusSuccess),
    api.post_check(lambda check, steps: check_child_build_output_properties(check, steps, True)),
    cq=True,
  )

  # Slim CQ build, with one gerrit_change.
  yield api.build_menu.test('slim-cq-build',
                            api.post_check(check_child_build_output_properties),
                            cq=True, build_target='atlas-slim')

  # This covers the env_info.pointless check.
  yield api.build_menu.test('pointless-cq-build', cq=True, pointless=True)

  # Release build.
  yield api.build_menu.test(
      'release-build',
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='cloudready-release-R90-13816.B')),
      build_target='cloudready-release-R90-13816.B', bucket='release')

  # Run the other tests that we only run in the module.
  yield api.build_menu.test(
      'postsubmit-build',
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/BuildSetup',
                                          '{"build_relevance": "UNKNOWN"}'),
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)),
      api.post_check(post_process.DoesNotRun, 'postsubmit relevance check'),
      input_properties={
          '$chromeos/build_menu': dict(artifact_build=True),
          '$chromeos/cros_relevance': dict(force_postsubmit_relevance=True),
      },
  )

  yield api.build_menu.test(
      'snapshot-build',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'postsubmit relevance check'),
  )

  yield api.build_menu.test('toolchain-cq-build',
                            api.build_menu.set_toolchain_cls_return(True),
                            cq=True)

  yield api.build_menu.test(
      'has-no-artifacts', input_properties={
          '$chromeos/cros_relevance': dict(force_postsubmit_relevance=True)
      }, build_target='arm-generic')

  yield api.build_menu.test(
      'postsubmit-with-changes', api.post_check(post_process.StatusFailure),
      api.post_check(post_process.DoesNotRun, 'cherry-pick gerrit changes'),
      build_target='arm-generic', cq=True, bucket='postsubmit')

  yield api.build_menu.test(
      'postsubmit-with-snapshot-prebuilts',
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)),
      input_properties={
          '$chromeos/build_menu':
              dict(artifact_build=True),
          '$chromeos/cros_relevance':
              dict(force_postsubmit_relevance=True),
          '$chromeos/cros_prebuilts':
              dict(enable_snapshot_prebuilts=True, send_snapshot_prebuilts=1)
      })

  for forced in False, True:
    yield api.build_menu.test(
        ('forced-' if forced else '') + 'pointless-artifact-build',
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
      'force-relevant-global-property',
      api.properties(FullProperties(forced_relevant=True)), cq=True,
      input_properties={'force_relevant_build': True})

  yield api.build_menu.test(
      'no-sysroot', api.properties(FullProperties(no_sysroot=True)),
      input_properties=({
          '$chromeos/cros_relevance': dict(force_postsubmit_relevance=True)
      }))

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
              '$chromeos/cros_relevance':
                  dict(force_postsubmit_relevance=True),
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
      api.properties(
          FullProperties(missing_config_ok=True, expect_missing_config=True)),
      builder='no-config')

  yield api.build_menu.test(
      'code-coverage-build', builder='sarien-code-coverage-postsubmit',
      build_target='sarien', input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True),
          '$chromeos/cros_relevance': dict(force_postsubmit_relevance=True)
      })

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-format',
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
      api.post_process(post_process.DropExpectation),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-characters',
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
      api.post_process(post_process.DropExpectation),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'bad-container-version-len',
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
      api.post_process(post_process.DropExpectation),
    cq=True,
  )

  # Cq build with bad container version string, should throw exception
  yield api.build_menu.test(
    'no-container-endpoint',
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
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),

    # Simulate a failure building a single container
    api.cros_build_api.set_api_return(
      'create test service containers',
      endpoint='TestService/BuildTestServiceContainers',
      data='{ "results": [ { "failure" : {} } ]}',
    ),
    cq=True,
  )

  yield api.build_menu.test(
    'buildtargetunittest-failure',
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    # Simulate a failure running unit tests
    api.cros_build_api.set_api_return(
      'run ebuild tests',
      endpoint='TestService/BuildTargetUnitTest',
      data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
    ),
    cq=True,
  )
