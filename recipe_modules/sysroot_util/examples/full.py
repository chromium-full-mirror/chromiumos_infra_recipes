# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'sysroot_util',
    'test_util',
]

import json

from PB.chromiumos import common
from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties
from PB.recipe_modules.chromeos.sysroot_util.examples.full import (
    FullTestProperties)

PROPERTIES = FullTestProperties


def RunSteps(api, properties):
  image_types = properties.image_types or [
      common.IMAGE_TYPE_BASE, common.IMAGE_TYPE_TEST
  ]
  image_test_json = properties.image_test_json

  name = properties.builder_name or 'amd64-generic-postsubmit'
  config = api.cros_infra_config.get_builder_config(name)

  sysroot = api.sysroot_util.create_sysroot(common.BuildTarget(name='eve'))
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

  api.sysroot_util.bootstrap_sysroot()

  dep_graph = api.cros_relevance.get_dependency_graph(sysroot, common.Chroot())
  api.sysroot_util.install_packages(config, dep_graph,
                                    artifact_build=properties.artifact_build)

  api.sysroot_util.build_images(image_types, 'builder/path', True, "big_disk",
                                test_test_data=image_test_json)


def GenTests(api):

  def test_build(build_target='amd64-generic', **kwargs):
    """Helper for creating build."""
    return api.test_util.test_child_build(build_target, **kwargs).build

  def goma_artifacts(with_goma=False):
    ret = dict(events=[{
        "name": "fake_package-path/fake-package-name-0.0.1-r2",
        "durationMilliseconds": "1523",
        "timestampMilliseconds": "1580481610805"
    }])
    if with_goma:
      ret['gomaArtifacts'] = {
          "counterzFile":
              "counterz.binaryproto",
          "statsFile":
              "stats.binaryproto",
          "logFiles": [
              "compiler_proxy-subproc.chromeos-ci.log.INFO.20200131.84.gz",
              "compiler_proxy.chromeos-ci.log.INFO.20200131-063322.81.gz",
              "gomacc.chromeos-ci.log.INFO.20200131-073921.1717.tar.gz",
              "ninja_log.chrome-bot.chromeos-ci-8owx.20200131-081005.8.gz"
          ]
      }
    return json.dumps(ret)

  yield api.test('basic', test_build())

  yield api.test('cq-build', test_build(cq=True))

  yield api.test(
      'sdk-test-build',
      test_build(
          cq=True, input_properties={
              '$chromeos/cros_sdk': dict(force_off_toolchain_changed=True)
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
      'fails-install-with-many-packages', test_build(cq=True),
      api.cros_build_api.set_api_return(
          'install packages', 'SysrootService/InstallPackages',
          json.dumps(
              dict(
                  failedPackages=[{
                      "category": "chromeos-base",
                      "packageName": "thislongpackagenameomg",
                      "version": "0.0.1-r199",
                  }, {
                      "category": "safari-base",
                      "packageName": "thisotherexceedinglylongpackage",
                      "version": "0.0.1-r129",
                  }, {
                      "category": "edge-base",
                      "packageName": "shortpackagename",
                      "version": "0.0.1-r197",
                  }], failedPackageData=[{
                      "name": {
                          "category": "chromeos-base",
                          "packageName": "thislongpackagenameomg",
                          "version": "0.0.1-r199",
                      },
                      "log_path": {
                          "path": "/all/your/package/are/belong/to/us",
                          "location": 1,
                      },
                  }, {
                      "name": {
                          "category": "safari-base",
                          "packageName": "thisotherexceedinglylongpackage",
                          "version": "0.0.1-r129",
                      },
                      "log_path": {
                          "path": "/all/your/ebuild/are/belong/to/us",
                          "location": 1,
                      },
                  }, {
                      "name": {
                          "category": "edge-base",
                          "packageName": "shortpackagename",
                          "version": "0.0.1-r197",
                      },
                      "log_path": {
                          "path": "/all/your/overlay/are/belong/to/us",
                          "location": 1,
                      },
                  }]))))

  yield api.test(
      'no-goma', test_build(),
      api.cros_build_api.set_api_return('install packages',
                                        'SysrootService/InstallPackages',
                                        goma_artifacts(False)))

  yield api.test(
      'with-goma', test_build(),
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
          FullTestProperties(
              use_remoteexec=True,
              builder_name='amd64-generic-postsubmit-remoteexec')))

  yield api.test('failed-image-test', test_build(),
                 api.properties(FullTestProperties(image_test_json='{}')))

  yield api.test(
      'no-base-image', test_build(),
      api.properties(FullTestProperties(image_types=[common.IMAGE_TYPE_TEST])))
