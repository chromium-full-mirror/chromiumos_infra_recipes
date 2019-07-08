# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.failures.failures import FailuresProperties

def RunSteps(api):
  # TODO(evanhernandez): Make this not depend on cros_som's test_api.
  build_critical_failure = build_pb2.Build(status=common_pb2.FAILURE)
  for _ in range(3):
    api.assertions.assertRaises(
        api.step.StepFailure, api.failures.raise_failed_builds,
        [build_critical_failure])

  # The fourth time should not raise.
  api.failures.raise_failed_builds([build_critical_failure])

def GenTests(api):
  yield api.test('basic')

  yield api.test('silences-disabled') + api.properties(
      **{'$chromeos/failures': FailuresProperties(disable_silences=True)})
