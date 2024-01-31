# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]



def RunSteps(api):
  api.cros_infra_config.set_build_criticality(
      critical=api.properties.get('critical'),
      override=api.properties.get('override'))
  api.assertions.assertEqual(api.buildbucket.build.critical,
                             api.properties.get('expected_critical'))


def GenTests(api):
  build = api.buildbucket.try_build_message()
  yield api.test(
      'previously-unset', api.buildbucket.build(build),
      api.properties(critical=common_pb2.Trinary.NO, override=False,
                     expected_critical=common_pb2.Trinary.NO))

  yield api.test('config-does-not-exist', api.buildbucket.build(build),
                 api.properties(expected_critical=common_pb2.Trinary.UNSET))

  build.builder.builder = 'atlas-cq'
  yield api.test('config-exists', api.buildbucket.build(build),
                 api.properties(expected_critical=common_pb2.Trinary.YES))

  build.critical = common_pb2.Trinary.NO
  yield api.test(
      'override', api.buildbucket.build(build),
      api.properties(critical=common_pb2.Trinary.YES, override=True,
                     expected_critical=common_pb2.Trinary.YES))

  yield api.test(
      'no-override', api.buildbucket.build(build),
      api.properties(critical=common_pb2.Trinary.YES, override=False,
                     expected_critical=common_pb2.Trinary.NO))
