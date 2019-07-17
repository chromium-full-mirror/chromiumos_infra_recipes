# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.failures.failures import FailuresProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
]


def assert_fatality(api, build, fatal):
  failures = api.failures.get_build_failures([build])
  api.assertions.assertEqual(len(failures), 1)
  failure = failures[0]
  api.assertions.assertEqual(failure.fatal, fatal)


def RunSteps(api):
  # TODO(evanhernandez): Make this not depend on cros_som's test_api.
  build_critical_failure = build_pb2.Build(
      builder=build_pb2.BuilderID(project='chromeos', bucket='bucket',
                                  builder='builder'), status=common_pb2.FAILURE)
  for _ in range(3):
    assert_fatality(api, build_critical_failure, True)

  # The fourth time should not raise unless disable_silences is true.
  assert_fatality(api, build_critical_failure, api.failures._disable_silences)

  # The fifth time is a success, but still silenced. This line just exercises
  # the code path that increments the silence counter.
  build_success = build_pb2.Build(
      builder=build_pb2.BuilderID(project='chromeos', bucket='bucket',
                                  builder='builder'), status=common_pb2.SUCCESS)
  api.failures.get_build_failures([build_success])

def GenTests(api):
  yield api.test('basic')

  yield api.test('silences-disabled') + api.properties(
      **{'$chromeos/failures': FailuresProperties(disable_silences=True)})
