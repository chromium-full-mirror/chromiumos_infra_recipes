# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
    'urls',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def build(**kwargs):
  return build_pb2.Build(
      builder=build_pb2.BuilderID(project='chromeos', bucket='bucket',
                                  builder='builder'), **kwargs)


def RunSteps(api):
  build_success = build(status=common_pb2.SUCCESS)
  build_failure = build(status=common_pb2.FAILURE, critical=common_pb2.NO)
  build_critical_failure = build(status=common_pb2.FAILURE,
                                 critical=common_pb2.YES)
  build_infra_failure = build(status=common_pb2.INFRA_FAILURE,
                              critical=common_pb2.NO)

  # Check boolean functions.
  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_success))
  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_build_failure(build_critical_failure))

  # Return only critical build failures.
  api.assertions.assertFalse(api.failures.get_build_failures([build_success]))
  api.assertions.assertFalse(api.failures.get_build_failures([build_failure]))
  api.assertions.assertEqual(
      api.failures.get_build_failures([build_critical_failure]), [
          api.failures.Failure(
              'build', 'builder',
              api.urls.get_build_link_map(build_critical_failure), True,
              'builder')
      ])
  api.assertions.assertFalse(
      api.failures.get_build_failures([build_infra_failure]))


def GenTests(api):
  yield api.test('basic')
