# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]



def RunSteps(api):
  api.assertions.assertIsNone(
      api.cros_infra_config.get_build_target_name(build_pb2.Build()))
  api.assertions.assertEqual(api.cros_infra_config.get_build_target_name(),
                             api.properties.get('expected_build_target'))


def GenTests(api):

  build = api.buildbucket.ci_build_message()
  yield api.test('no-build-target', api.buildbucket.build(build))

  build = api.buildbucket.ci_build_message()
  build.input.properties['buildTarget'] = {'name': 'tast-vm-target'}
  yield api.test('tast-vm-props', api.buildbucket.build(build),
                 api.properties(expected_build_target='tast-vm-target'))

  build.input.properties['$chromeos/build_menu'] = {
      'build_target': {
          'name': 'build-menu-target'
      }
  }
  yield api.test('build-menu-props', api.buildbucket.build(build),
                 api.properties(expected_build_target='build-menu-target'))
