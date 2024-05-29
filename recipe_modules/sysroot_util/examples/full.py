# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api import depgraph
from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties
from PB.recipe_modules.chromeos.sysroot_util.examples.full import FullTestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'chrome',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'sysroot_util',
    'test_util',
    'workspace_util',
]


PROPERTIES = FullTestProperties


def RunSteps(api, properties):
  # Changes need to be applied for fault attribution.
  api.workspace_util.apply_changes()
  image_types = properties.image_types or [
      common.IMAGE_TYPE_BASE, common.IMAGE_TYPE_TEST
  ]
  # Use UNDEFINED as a "no types" indicator.
  if image_types == [common.IMAGE_TYPE_UNDEFINED]:
    image_types = []

  image_test_json = properties.image_test_json

  name = properties.builder_name or 'amd64-generic-snapshot'
  config = api.cros_infra_config.get_builder_config(name)

  target = common.BuildTarget(name='eve')
  sysroot = api.sysroot_util.create_sysroot(target)
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

  api.sysroot_util.bootstrap_sysroot()

  dep_graph = api.cros_relevance.get_dependency_graph(sysroot, common.Chroot())
  if properties.checkout_chrome:
    api.chrome.sync_chrome_async(config, target)
  api.sysroot_util.install_packages(config, dep_graph,
                                    artifact_build=properties.artifact_build)

  api.sysroot_util.build_images(
      image_types, 'builder/path', disable_rootfs_verification=True,
      disk_layout='big_disk', base_is_recovery=properties.base_is_recovery,
      test_test_data=image_test_json, skip_image_tests=properties.skip_tests,
      verify_image_size_delta=properties.verify_image_size_delta,
      is_official=properties.is_official)


def GenTests(api):

  def test_build(build_target='amd64-generic', **kwargs):
    """Helper for creating build."""
    return api.test_util.test_child_build(build_target, **kwargs).build

  def goma_artifacts(with_goma=False):
    ret = {
        'events': [{
            'name': 'fake_package-path/fake-package-name-0.0.1-r2',
            'durationMilliseconds': '1523',
            'timestampMilliseconds': '1580481610805'
        }]
    }
    if with_goma:
      ret['gomaArtifacts'] = {
          'counterzFile':
              'counterz.binaryproto',
          'statsFile':
              'stats.binaryproto',
          'logFiles': [
              'compiler_proxy-subproc.chromeos-ci.log.INFO.20200131.84.gz',
              'compiler_proxy.chromeos-ci.log.INFO.20200131-063322.81.gz',
              'gomacc.chromeos-ci.log.INFO.20200131-073921.1717.tar.gz',
              'ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005.8.gz'
          ]
      }
    return api.json.dumps(ret, sort_keys=True)

  def create_image_events(rootfs_size):
    ret = {}
    if rootfs_size:
      ret['events'] = [{
          'name': 'board.total_size.base.rootfs',
          'gauge': str(rootfs_size),
          'timestampMilliseconds': '1580481610805'
      }]
    return api.json.dumps(ret, sort_keys=True)

  def get_buildbucket_simulated_search_results(rootfs_size):
    """Get buildbucket simulated search results for finding child builders.

    Args:
      size (int): Size to set.

    Returns:
      (TestData): Test data for 'buildbucket.search' step.
    """
    results = []
    if rootfs_size:
      output = build_pb2.Build.Output()
      output.properties['rootfs_size'] = rootfs_size
      results.append(build_pb2.Build(id=101, output=output))
    return api.buildbucket.simulated_search_results(
        results, 'build images.image size regression check.'
        'fetch last recorded rootfs size.buildbucket.search')

  yield api.test('basic', test_build())

  yield api.test(
      'chrome-cache-experiment',
      test_build(),
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.sysroot_util.chrome_cache']),
  )

  yield api.test(
      'clean-incrementals-experiment',
      test_build(),
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.sysroot_util.clean_incrementals']),
  )

  yield api.test(
      'chrome-cache-experiment-with-purge',
      test_build(),
      api.buildbucket.ci_build(
          builder='atlas-cq', experiments=[
              'chromeos.sysroot_util.chrome_cache',
              'chromeos.sysroot_util.chrome_cache_purge'
          ]),
      api.post_process(post_process.MustRun,
                       'install packages.deleting chrome checkout'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test('cq-build', test_build(cq=True))

  yield api.test(
      'no-image-types', test_build(),
      api.properties(
          FullTestProperties(image_types=[common.IMAGE_TYPE_UNDEFINED])))

  yield api.test(
      'sdk-test-build',
      test_build(
          cq=True, input_properties={
              '$chromeos/cros_sdk': {
                  'force_off_toolchain_changed': True
              },
          }))

  yield api.test('artifact-build', test_build(),
                 api.properties(FullTestProperties(artifact_build=True)))

  yield api.test(
      'cq-build-no-chrome-source',
      test_build(cq=True),
      api.cros_build_api.set_api_return(
          'install packages.check chrome source needed',
          'PackageService/NeedsChromeSource', '{"needs_chrome_source": false}'),
  )

  yield api.test(
      'no-chrome-source-experiment-enabled',
      test_build(cq=True),
      api.properties(FullTestProperties(checkout_chrome=True)),
      api.buildbucket.ci_build(builder='atlas-cq', experiments=[
          'chromeos.build_menu.chrome_sync',
      ]),
      api.cros_build_api.set_api_return(
          'install packages.check chrome source needed',
          'PackageService/NeedsChromeSource', '{"needs_chrome_source": false}'),
      api.post_check(
          post_process.StepSuccess,
          'install packages.check chrome source needed.deleting chrome checkout'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fails-install-with-many-packages',
      test_build(cq=True),
      test_build(cq=True),
      api.cros_build_api.set_api_return(
          'install packages.get package dependencies', 'DependencyService/List',
          json_format.MessageToJson(
              depgraph.ListResponse(package_deps=[
                  common.PackageInfo(category='chromeos-base',
                                     package_name='thislongpackagenameomg',
                                     version='0.0.1-r199')
              ]))),
      api.cros_build_api.set_api_return(
          'install packages', 'SysrootService/InstallPackages',
          api.json.dumps(
              {
                  'failedPackageData': [{
                      'name': {
                          'category': 'chromeos-base',
                          'packageName': 'thislongpackagenameomg',
                          'version': '0.0.1-r199',
                      },
                      'log_path': {
                          'path': '/all/your/package/are/belong/to/us',
                          'location': 1,
                      },
                  }, {
                      'name': {
                          'category': 'safari-base',
                          'packageName': 'thisotherexceedinglylongpackage',
                          'version': '0.0.1-r129',
                      },
                      'log_path': {
                          'path': '/all/your/ebuild/are/belong/to/us',
                          'location': 1,
                      },
                  }, {
                      'name': {
                          'category': 'edge-base',
                          'packageName': 'shortpackagename',
                          'version': '0.0.1-r197',
                      },
                      'log_path': {
                          'path': '/all/your/overlay/are/belong/to/us',
                          'location': 1,
                      },
                  }]
              }, sort_keys=True)),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'no-goma', test_build(),
      api.cros_build_api.set_api_return('install packages',
                                        'SysrootService/InstallPackages',
                                        goma_artifacts(False)))

  yield api.test(
      'with-goma', test_build(),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.cros_build_api.set_api_return('install packages',
                                        'SysrootService/InstallPackages',
                                        goma_artifacts(True)))

  yield api.test(
      'with-remoteexec', test_build(),
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reproxy_cfg_file='reclient_cfgs/reproxy_config.cfg',
                      reclient_version='release',
                  )
          }),
      api.properties(
          FullTestProperties(use_remoteexec=True,
                             builder_name='amd64-generic-snapshot-remoteexec')))

  yield api.test(
      'failed-image-test',
      test_build(),
      api.properties(FullTestProperties(image_test_json='{}')),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'no-base-image', test_build(),
      api.properties(FullTestProperties(image_types=[common.IMAGE_TYPE_TEST])))

  yield api.test(
      'with-factory-image',
      test_build(),
      api.properties(
          FullTestProperties(image_types=[
              common.IMAGE_TYPE_BASE,
              common.IMAGE_TYPE_TEST,
              common.IMAGE_TYPE_FACTORY,
          ]), is_official=True),
      api.post_process(
          post_process.DoesNotRun,
          'build images.Running `make_netboot.sh` for legacy factory branch'),
  )

  yield api.test('base-is-recovery', test_build(),
                 api.properties(base_is_recovery=True))

  yield api.test(
      'skip-image-tests', test_build(), api.properties(skip_tests=True),
      api.post_process(
          post_process.DoesNotRun,
          'build images.test images.call chromite.api.ImageService/Test'))

  yield api.test(
      'image-size', test_build(),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=2**30)),
      api.post_process(post_process.PropertyEquals, 'rootfs_size', 2**30))

  yield api.test(
      'image-size-regression-check-no-rootfs-size', test_build(),
      api.properties(verify_image_size_delta=True),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=0)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'No rootfs size found for current build.',
      ))

  yield api.test(
      'image-size-regression-check-no-reference-size', test_build(),
      api.properties(verify_image_size_delta=True),
      get_buildbucket_simulated_search_results(0),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=2**30)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'No previous rootfs size found.',
      ))

  yield api.test(
      'image-size-regression-check-decrease', test_build(),
      api.properties(verify_image_size_delta=True),
      get_buildbucket_simulated_search_results(rootfs_size=2**30),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=2**29)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'Estimated 512.0MiB rootfs size decrease.',
      ), api.post_process(post_process.PropertyEquals, 'rootfs_delta', -2**29))

  yield api.test(
      'image-size-regression-check-increase', test_build(),
      api.properties(verify_image_size_delta=True),
      get_buildbucket_simulated_search_results(rootfs_size=2**29),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=2**30)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'Estimated 512.0MiB rootfs size increase.',
      ), api.post_process(post_process.PropertyEquals, 'rootfs_delta', 2**29))

  yield api.test(
      'image-size-regression-check-increase-small', test_build(),
      api.properties(verify_image_size_delta=True),
      get_buildbucket_simulated_search_results(rootfs_size=2**30),
      api.cros_build_api.set_api_return(
          'build images', 'ImageService/Create',
          create_image_events(rootfs_size=2**30 + 1)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'Estimated 1B rootfs size increase.',
      ), api.post_process(post_process.PropertyEquals, 'rootfs_delta', 1))

  yield api.test(
      'image-size-regression-check-no-change', test_build(),
      api.properties(verify_image_size_delta=True),
      get_buildbucket_simulated_search_results(rootfs_size=2**30),
      api.cros_build_api.set_api_return('build images', 'ImageService/Create',
                                        create_image_events(rootfs_size=2**30)),
      api.post_process(
          post_process.StepTextEquals,
          'build images.image size regression check',
          'No rootfs size delta.',
      ), api.post_process(post_process.PropertyEquals, 'rootfs_delta', 0))

  yield api.test(
      'remoteexec-logs-upload',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(enable_logs_upload=True,
                                       reproxy_cfg_file='reproxy_release.cfg')
          }))

  yield api.test(
      'factory-image-without-create-netboot-endpoint',
      test_build(),
      api.properties(
          FullTestProperties(image_types=[
              common.IMAGE_TYPE_FACTORY,
          ])),
      api.cros_build_api.remove_endpoints(['ImageService/CreateNetboot']),
      api.post_process(
          post_process.MustRun,
          'build images.Running `make_netboot.sh` for legacy factory branch'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test('toolchain-CL-add-thinlto',
                 api.cros_relevance.toolchain_cls_applied(True),
                 test_build(cq=True))

  yield api.test('non-toolchain-CL-no-thinlto',
                 api.cros_relevance.toolchain_cls_applied(False),
                 test_build(cq=True))
