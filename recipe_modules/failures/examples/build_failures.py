# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

def RunSteps(api):
  build_success = build_pb2.Build(id=101, status=common_pb2.SUCCESS)
  build_failure = build_pb2.Build(id=202,
                                  status=common_pb2.FAILURE,
                                  critical=common_pb2.NO)
  build_critical_failure = build_pb2.Build(id=303, status=common_pb2.FAILURE)

  # Check boolean functions.
  api.assertions.assertFalse(api.failures.is_build_failure(build_success))
  api.assertions.assertTrue(api.failures.is_build_failure(build_failure))
  api.assertions.assertTrue(
      api.failures.is_build_failure(build_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_success))
  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_build_failure(build_critical_failure))

  # Raise on critical build failures.
  api.failures.raise_failed_builds([build_success])
  api.failures.raise_failed_builds([build_failure])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_builds,
                              [build_critical_failure, build_critical_failure])

def GenTests(api):
  yield api.test('basic')
