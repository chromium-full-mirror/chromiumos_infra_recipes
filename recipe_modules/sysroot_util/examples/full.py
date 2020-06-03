# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_relevance',
    'sysroot_util',
]

from PB.chromiumos import common
from PB.recipe_modules.chromeos.sysroot_util.examples.full import (
    FullTestProperties)

PROPERTIES = FullTestProperties


def RunSteps(api, properties):
  image_types = properties.image_types or [common.BASE, common.TEST]
  image_test_json = properties.image_test_json

  config = api.cros_infra_config.get_builder_config('amd64-generic-postsubmit')

  sysroot = api.sysroot_util.create_sysroot(common.BuildTarget(name='eve'))
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

  api.sysroot_util.bootstrap_sysroot()

  dep_graph = api.cros_relevance.get_dependency_graph(sysroot, common.Chroot())
  api.sysroot_util.install_packages(config, dep_graph,
                                    artifact_build=properties.artifact_build)

  api.sysroot_util.build_images(image_types, 'builder/path', True, "big_disk",
                                test_test_data=image_test_json)


def GenTests(api):
  yield api.test('basic')

  yield api.test('artifact-build',
                 api.properties(FullTestProperties(artifact_build=True)))

  yield api.test('failed-image-test',
                 api.properties(FullTestProperties(image_test_json='{}')))

  yield api.test('no-base-image',
                 api.properties(FullTestProperties(image_types=[common.TEST])))
