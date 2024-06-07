# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api import depgraph
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.build_menu.examples.full import FullProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_history',
    'cros_relevance',
    'cros_version',
    'gerrit',
    'repo',
    'test_util',
]


PROPERTIES = FullProperties


def RunSteps(api, properties):
  with api.build_menu.configure_builder(
      missing_ok=properties.missing_config_ok) as config:
    api.assertions.assertEqual(config, api.build_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      api.assertions.assertIsNotNone(api.build_menu.config_or_default)
      return
    DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  cherry_pick_changes = not properties.dont_cherry_pick_changes
  with api.build_menu.setup_workspace_and_chroot(
      cherry_pick_changes=cherry_pick_changes):
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        not properties.no_sysroot,
        sysroot_archive=properties.sysroot_archive_gs_path or None)
    # pylint: disable=protected-access
    api.assertions.assertEqual(properties.forced_relevant,
                               api.build_menu._force_relevant_build)

    if properties.no_sysroot:
      api.assertions.assertIsNone(api.build_menu.sysroot)
    else:
      api.build_menu.bootstrap_sysroot()
      api.build_menu.install_packages()
      api.build_menu.build_and_test_images(config)
      api.build_menu.build_and_test_images(include_version=True)
      api.build_menu.get_cl_affected_sysroot_packages()
      # TODO(b/277222525): Separate uploads into a separate test case.
      if properties.upload_prebuilts:
        api.build_menu.upload_prebuilts()
      if properties.upload_devinstall_prebuilts:
        api.build_menu.upload_devinstall_prebuilts()
      if properties.upload_chrome_prebuilts:
        api.build_menu.upload_chrome_prebuilts()
      if properties.upload_host_prebuilts:
        api.build_menu.upload_host_prebuilts()
      _ = api.build_menu.artifacts_gs_path()
      api.build_menu.upload_artifacts()
      api.build_menu.create_containers()
      if properties.publish_image_sizes:
        api.build_menu.publish_image_size_data(config)

    # Sometimes these are RepeatedCompositeFieldContainter, sometimes they are
    # list.  Cast them.
    api.assertions.assertEqual(
        list(env_info.packages), list(properties.expected_packages))

    if config and config.id.type == BuilderConfig.Id.Type.RELEASE:
      api.build_menu.publish_latest_files('bucket', '{gs_path}')


def step_data_no_cached_container_gcs(api):
  return api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.gsutil list',
      stdout=api.raw_io.output_text(None), retcode=0)


def step_data_complete_cached_container_gcs(api):

  test_data_complete = api.json.dumps({'status': 'completed'})
  step_data_ls_attempt_1 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.gsutil list',
      stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json
      '''), retcode=0)
  step_data_cat_attempt_1 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.reading cached container info from gs path: gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json.gsutil cat',
      stdout=api.raw_io.output_text(test_data_complete))
  return step_data_ls_attempt_1, step_data_cat_attempt_1


def step_data_incomplete_cached_container_gcs(api):

  test_data_incomplete = api.json.dumps({'status': 'started'})

  step_data_ls_attempt_1 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.gsutil list',
      stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json
      '''), retcode=0)
  step_data_cat_attempt_1 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.reading cached container info from gs path: gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json.gsutil cat',
      stdout=api.raw_io.output_text(test_data_incomplete))
  step_data_ls_attempt_2 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-2.gsutil list',
      stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json
      '''), retcode=0)
  step_data_cat_attempt_2 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-2.reading cached container info from gs path: gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json.gsutil cat',
      stdout=api.raw_io.output_text(test_data_incomplete))
  step_data_ls_attempt_3 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-3.gsutil list',
      stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json
      '''), retcode=0)
  step_data_cat_attempt_3 = api.step_data(
      'create test service containers.cached container info from gcs.attempt-3.reading cached container info from gs path: gs://chromeos-image-archive/cft-container-json/8766842719767962417/led.json.gsutil cat',
      stdout=api.raw_io.output_text(test_data_incomplete))
  return step_data_ls_attempt_1, step_data_cat_attempt_1, step_data_ls_attempt_2, step_data_cat_attempt_2, step_data_ls_attempt_3, step_data_cat_attempt_3


def GenTests(api):

  step_data_complete_ls_attempt_1, step_data_complete_cat_attempt_1 = step_data_complete_cached_container_gcs(
      api)
  step_data_ls_attempt_1, step_data_cat_attempt_1, step_data_ls_attempt_2, step_data_cat_attempt_2, step_data_ls_attempt_3, step_data_cat_attempt_3 = step_data_incomplete_cached_container_gcs(
      api)

  yield api.build_menu.test(
      'cq-build-no-experiment',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      cq=True,
  )

  yield api.build_menu.test(
      'cq-build-with-no-gcs-cache',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      api.cros_version.workspace_version('R126-15870.0.0'),
      step_data_no_cached_container_gcs(api),
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'cq-build-with-complete-gcs-cache',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          ),
      ),
      api.cros_version.workspace_version('R126-15870.0.0'),
      step_data_complete_ls_attempt_1,
      step_data_complete_cat_attempt_1,
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'cq-build-with-incomplete-gcs-cache',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          ),
      ),
      api.cros_version.workspace_version('R126-15870.0.0'),
      step_data_ls_attempt_1,
      step_data_cat_attempt_1,
      step_data_ls_attempt_2,
      step_data_cat_attempt_2,
      step_data_ls_attempt_3,
      step_data_cat_attempt_3,
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'cq-build-with-cft-cache-gsutil-timeout',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          ),
      ),
      api.cros_version.workspace_version('R126-15870.0.0'),
      # the value for times_out_after should be greater than what is defined in the gsutil call
      api.step_data(
      'create test service containers.cached container info from gcs.attempt-1.gsutil list',
      stdout=api.raw_io.output_text(''), times_out_after=61),
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'cq-build-with-cache-build-supported-build-version',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          ),
      ),
      api.cros_version.workspace_version('R126-15870.0.0'),
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'cq-build-with-cache-build-unsupported-build-version',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='atlas',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          ),
      ),
      api.cros_version.workspace_version('R126-15869.0.0'),
      cq=True,
      build_target='atlas',
      experiments=['chromeos.build_cq.cft_cache_build'],
  )

  yield api.build_menu.test(
      'push-cft-containers-to-publicbuilds-repository-for-builds-running-on-public-builder-bots',
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='eve',
          container_version_format='{staging?}{build-target}-cq.{cros-version}-{bbid}',
      )),
      api.post_process(
          post_process.LogContains,
          'create test service containers.call chromite.api.TestService/BuildTestServiceContainers',
          'request',
          ['"project": "cros-registry/test-services-publicbuilds"'],
      ),
      cq=True,
      builder_name='eve-main-public',
  )

  yield api.build_menu.test(
      'staging-cq-build',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='staging-amd64-generic',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      build_target='staging-amd64-generic',
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
    cq=True,
  )


  # Slim CQ build, with one gerrit_change.
  yield api.build_menu.test('slim-cq-build',
                            cq=True, build_target='atlas-slim')

  # This covers the env_info.pointless check.
  yield api.build_menu.test('pointless-cq-build', cq=True, pointless=True)

  # Release build.
  yield api.build_menu.test(
      'release-build',
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='cloudready-release-R90-13816.B')),
      input_properties={
          '$chromeos/cros_artifacts': {
              'gs_upload_path': '{target}-release/{version}',
          },
      }, build_target='cloudready-release-R90-13816.B', bucket='release')

  # Release build with devinstall prebuilts.
  yield api.build_menu.test(
      'release-build-prebuilts',
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='cloudready-release-R90-13816.B')),
      api.properties(FullProperties(upload_devinstall_prebuilts=True)),
      api.post_check(post_process.MustRun, 'upload devinstall prebuilts'),
      input_properties={
          '$chromeos/cros_artifacts': {
              'gs_upload_path': '{target}-release/{version}',
          },
      }, build_target='cloudready-release-R90-13816.B', bucket='release')

  # Run the other tests that we only run in the module.
  yield api.build_menu.test(
      'postsubmit-build',
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/BuildSetup',
                                          '{"build_relevance": "UNKNOWN"}'),
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True)),
      api.post_check(post_process.DoesNotRun, 'postsubmit relevance check'),
      api.build_menu.assert_step_uses_portage('install packages',
                                              'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_portage('build images',
                                              'ImageService/Create'),
      api.build_menu.assert_step_uses_portage(
          'run ebuild tests', 'TestService/BuildTargetUnitTest'),
      input_properties={
          '$chromeos/build_menu': {
              'artifact_build': True
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      },
  )

  yield api.build_menu.test(
      'postsubmit-build-with-bazel',
      api.build_menu.assert_step_uses_bazel('install packages',
                                            'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_bazel('build images',
                                            'ImageService/Create'),
      api.build_menu.assert_step_uses_bazel('run ebuild tests',
                                            'TestService/BuildTargetUnitTest'),
      builder_name='amd64-generic-bazel-snapshot',
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
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      }, build_target='arm-generic')

  yield api.build_menu.test(
      'postsubmit-with-changes',
      api.post_check(post_process.DoesNotRun, 'cherry-pick gerrit changes'),
      build_target='arm-generic',
      cq=True,
      bucket='postsubmit',
      status='FAILURE',
  )

  # Ensure CQ uploads the prebuilts if the prebuilt target is PUBLIC.
  yield api.build_menu.test(
      'cq-with-uploading-prebuilts',
      api.test_util.test_orchestrator(bucket='cq').build,
      api.properties(FullProperties(upload_prebuilts=True)),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      input_properties={
          '$chromeos/build_menu': {
              'override_prebuilts_config': BuilderConfig.Artifacts.PUBLIC
          },
      }, cq=True)

  # Ensure CQ does not upload the prebuilts if the prebuilt target is NONE.
  yield api.build_menu.test(
      'cq-without-uploading-prebuilts',
      api.test_util.test_orchestrator(bucket='cq').build,
      api.properties(FullProperties(upload_prebuilts=True)),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      input_properties={
          '$chromeos/build_menu': {
              'override_prebuilts_config': BuilderConfig.Artifacts.NONE,
          },
      }, cq=True)

  yield api.build_menu.test(
      'uploads-chrome-prebuilts',
      api.properties(FullProperties(upload_chrome_prebuilts=True)),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      input_properties={
          '$chromeos/build_menu': {
              'override_prebuilts_config': BuilderConfig.Artifacts.PUBLIC,
          }
      }, cq=True)

  yield api.build_menu.test(
      'uploads-host-prebuilts',
      api.properties(FullProperties(upload_host_prebuilts=True)),
      api.post_check(post_process.MustRun, 'upload host prebuilts'))

  yield api.build_menu.test(
      'postsubmit-with-snapshot-prebuilts',
      api.properties(
          FullProperties(artifact_build=True, upload_prebuilts=True,
                         publish_image_sizes=True)), input_properties={
                             '$chromeos/build_menu': {
                                 'artifact_build': True
                             },
                             '$chromeos/cros_relevance': {
                                 'force_postsubmit_relevance': True
                             },
                         })

  for forced in False, True:
    yield api.build_menu.test(
        ('forced-' if forced else '') + 'pointless-artifact-build',
        api.properties(
            FullProperties(
                build_target=common.BuildTarget(name='sarien'),
                artifact_build=True, forced_relevant=forced,
                expected_packages=[])), build_target='sarien',
        builder='build-code-coverage-brya-informational',
        artifact_pointless=True, input_properties={
            '$chromeos/build_menu': {
                'artifact_build': True,
                'force_relevant_build': forced,
            },
        })

  yield api.build_menu.test(
      'force-relevant-global-property',
      api.properties(FullProperties(forced_relevant=True)), cq=True,
      input_properties={'force_relevant_build': True})

  yield api.build_menu.test(
      'no-sysroot', api.properties(FullProperties(no_sysroot=True)),
      input_properties=({
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      }))

  yield api.build_menu.test(
      'chrome-sync-experiment-on',
      api.properties(FullProperties(no_sysroot=True)),
      api.buildbucket.ci_build(builder='atlas-cq', experiments=[
          'chromeos.build_menu.chrome_sync',
      ]), api.post_check(post_process.StepSuccess, 'sync chrome source async'),
      api.post_process(post_process.DropExpectation), input_properties=({
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      }))

  yield api.build_menu.test(
      'no-config',
      builder='no-config',
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.build_menu.test(
      'missing-ok-config',
      api.properties(
          FullProperties(missing_config_ok=True, expect_missing_config=True)),
      builder='no-config')

  yield api.build_menu.test(
      'code-coverage-build', builder='build-code-coverage-brya-informational',
      build_target='sarien', input_properties={
          '$chromeos/build_menu': {
              'test_with_code_coverage': True
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
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
    api.post_check(
      post_process.ResultReasonRE,
      'Unknown fields found in version format string',
    ),
      api.post_process(post_process.DropExpectation),
    cq=True,
    status='INFRA_FAILURE',
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
    api.post_check(
      post_process.ResultReasonRE,
      'Invalid tag format',
    ),
      api.post_process(post_process.DropExpectation),
    cq=True,
    status='INFRA_FAILURE',
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
    api.post_check(
      post_process.ResultReasonRE,
      'Tag is too long',
    ),
      api.post_process(post_process.DropExpectation),
    cq=True,
    status='INFRA_FAILURE',
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
    # TODO (b/275363240): audit this test.
    status='FAILURE',
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
      api.cros_build_api.set_api_return(
          'run ebuild tests.get package dependencies', 'DependencyService/List',
          json_format.MessageToJson(
              depgraph.ListResponse(package_deps=[
                  common.PackageInfo(category='foo',
                                     package_name='bar',
                                     version='1.0-r1')
              ]))),
    cq=True,
    status='FAILURE',
  )

  yield api.test(
      'ebuild-tests-no-relevant-packages',
      api.buildbucket.try_build(
          builder='atlas-slim-cq', gerrit_changes=[
              GerritChange(host='chrome-internal-review.googlesource.com',
                           project='project-a', change=1235)
          ]),
      api.properties(**{'$recipe_engine/cv': {
          'active': True
      }}),
      api.cros_build_api.set_api_return('get package dependencies',
                                        endpoint='DependencyService/List',
                                        data='{}'),
      api.post_check(post_process.MustRun, 'get package dependencies'),
      api.post_check(
          post_process.DoesNotRun,
          'run ebuild tests.call chromite.api.TestService/BuildTargetUnitTest'),
  )

  gerrit_changes = [
      GerritChange(host='chrome-internal-review.googlesource.com',
                   project='chromeos/manifest-internal', change=1235)
  ]
  yield api.test(
      'ebuild-tests-manifest-change',
      api.buildbucket.try_build(builder='cave-slim-cq',
                                gerrit_changes=gerrit_changes),
      api.repo.project_infos_step_data('run ebuild tests.get affected paths', [{
          'project': 'chromeos/manifest-internal',
          'path': 'manifest-internal'
      }]),
      api.repo.project_infos_step_data(
          'run ebuild tests (2).get affected paths', [{
              'project': 'chromeos/manifest-internal',
              'path': 'manifest-internal'
          }]),
      api.gerrit.set_gerrit_fetch_changes_response(
          'cherry-pick gerrit changes', gerrit_changes, {
              1235: {
                  'files': {
                      'a/b/d/test.txt': {},
                      'otherfile.xml': {}
                  },
              },
          }, iteration=1),
      api.properties(**{'$recipe_engine/cv': {
          'active': True
      }}),
      api.post_process(post_process.StepTextEquals, 'run ebuild tests',
                       'running all unit tests on manifest changes'),
      api.post_check(
          post_process.MustRun,
          'run ebuild tests.call chromite.api.TestService/BuildTargetUnitTest'),
  )

  gerrit_changes = [
      GerritChange(host='chromium-review.googlesource.com',
                   project='chromiumos/overlays/chromiumos-overlay',
                   change=1235)
  ]
  yield api.test(
      'ebuild-tests-toolchain-change',
      api.buildbucket.try_build(builder='cave-slim-cq',
                                gerrit_changes=gerrit_changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'cherry-pick gerrit changes', gerrit_changes, {
              1235: {
                  'files': {
                      'sys-devel/llvm/llvm-9999.ebuild': {},
                  },
              },
          }, iteration=1),
      api.cros_relevance.toolchain_cls_applied(True),
      api.properties(**{'$recipe_engine/cv': {
          'active': True
      }}),
      api.post_process(post_process.StepTextEquals, 'run ebuild tests',
                       'running all unit tests on toolchain changes'),
      api.post_check(
          post_process.MustRun,
          'run ebuild tests.call chromite.api.TestService/BuildTargetUnitTest'),
  )

  yield api.build_menu.test(
    'code-coverage-builder',
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='sarien-code-coverage',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          data=('{"artifacts": {"test": {"artifacts": [{"artifact_type":"CODE_COVERAGE_LLVM_JSON",'
                '"paths": [{"path":"[CLEANUP]/generated/code_coverage.tbz2"}],'
                '"location": "PLATFORM_EC"}]}}}')),
    api.post_check(post_process.MustRun,
          'upload artifacts.upload code coverage data'),
    cq=True,
  )

  yield api.build_menu.test(
    'rust-code-coverage-builder',
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='sarien-code-coverage',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          data=('{"artifacts": {"test": {"artifacts": [{"artifact_type":"CODE_COVERAGE_RUST_LLVM_JSON",'
                '"paths": [{"path":"[CLEANUP]/generated/code_coverage.tbz2"}],'
                '"location": "PLATFORM_EC"}]}}}')),
    api.post_check(post_process.MustRun,
          'upload artifacts.upload code coverage data'),
    cq=True,
  )

  yield api.build_menu.test(
      'skip_unit_tests',
      api.properties(**api.test_util.build_menu_properties(
          build_target_name='sarien-code-coverage',
          skip_unit_tests=True,
      )), api.post_check(post_process.DoesNotRun, 'run ebuild tests'))

  yield api.build_menu.test(
    'golang-code-coverage-builder',
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='sarien-code-coverage',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          data=('{"artifacts": {"test": {"artifacts": [{"artifact_type":"CODE_COVERAGE_GOLANG",'
                '"paths": [{"path":"[CLEANUP]/generated/code_coverage_go.tbz2"}],'
                '"location": "PLATFORM_EC"}]}}}')),
    api.post_check(post_process.MustRun,
          'upload artifacts.upload code coverage data'),
    cq=True,
  )

  yield api.build_menu.test(
    'code-coverage-builder-failure',
    api.properties(
      **api.test_util.build_menu_properties(
        build_target_name='atlas',
        container_version_format=\
        '{staging?}{build-target}-cq.{cros-version}-{bbid}'
      )
    ),
    # Simulate a failure when installing packages.
    api.cros_build_api.set_api_return(
      'install packages',
      endpoint='SysrootService/InstallPackages',
      data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
    ),
    api.post_check(
          post_process.DoesNotRun,
          'upload artifacts.upload code coverage data'
      ),
    cq=True,
    # TODO (b/275363240): audit this test.
    status='FAILURE',
  )

  yield api.build_menu.test(
      'validate-sdk-reuse-failures',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='amd64-generic',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      api.step_data('validate SDK reuse.depgraph relevance check.run check', retcode=1),
      api.step_data('validate SDK reuse (2).depgraph relevance check.run check', retcode=1),
      api.post_check(post_process.PropertyEquals, 'sdk_state', 'DIRTY'),
      api.post_process(post_process.DropExpectation),
      build_target='amd64-generic',
      cq=True,
  )

  yield api.build_menu.test(
      'use-sysroot-archive',
      api.properties(
          **api.test_util.build_menu_properties(
            build_target_name='amd64-generic',
            container_version_format=\
              '{staging?}{build-target}-cq.{cros-version}-{bbid}'
          )
      ),
      api.properties(
          FullProperties(
              sysroot_archive_gs_path='gs://foo/board1/R120-15650.0.0-abc/sysroot.tar.xz'
          )),
      api.post_check(post_process.MustRun, 'extract sysroot archive'),
  )
