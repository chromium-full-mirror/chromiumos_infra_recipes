# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import functools

from google.protobuf import duration_pb2

from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan',
    'metadata',
    'skylab',
]



def RunSteps(api):
  # Run with non-existent build target to trigger error path
  hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'my_first_little_hwtest'
  hw_test.run_via_cft = True
  hw_test.run_via_trv2 = True
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  api.skylab.schedule_suites(
      [
          unit_hw_test,
      ],
      timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(
          target='non-existent-target',
      ),
  )


def GenTests(api):

  require_step = functools.partial(api.post_check, post_process.MustRunRE)

  yield api.test(
      'no_build_target',
      api.properties(**{
          '$chromeos/skylab': SkylabProperties(
              enable_container_support=True,
          )
      }),
      require_step('.*configure test-builder'),
      api.post_check(
          post_process.StepSummaryEquals,
          'schedule skylab tests v2.create test requests.configure test-builder',
          "Execution via container requested, but no container metadata for build target 'another_target'",
      ),
      api.post_process(
          post_process.DoesNotRun,
          'schedule skylab tests v2.buildbucket.schedule',
      ),
  )
