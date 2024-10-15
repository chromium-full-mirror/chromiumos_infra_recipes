# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests `should_generate_lkgm_cl()` method in `snapshot_orch_menu` module.
"""

from google.protobuf import timestamp_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'failures',
    'snapshot_orch_menu',
    'test_util',
]


def RunSteps(api):
  # Set intial build status values.
  api.snapshot_orch_menu.should_generate_lkgm_cl()


def GenTests(api):
  SIMULATED_CURRENT_TIME = 1717214400  # Sun Jun 01 2024 04:00:00 GMT+0000
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties['lkgm'] = {
      'uprev_cl_generated': True,
      'uprev_dryrun': False,
  }

  builds = [
      build_pb2.Build(
          builder=builder_common_pb2.BuilderID(
              project='chromeos',
              bucket='postsubmit',
              builder='snapshot-orchestrator',
          ),
          end_time=timestamp_pb2.Timestamp(seconds=SIMULATED_CURRENT_TIME -
                                           6 * 60 * 60),
          output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
      ),
  ]
  yield api.test(
      'basic',
      api.time.seed(SIMULATED_CURRENT_TIME),
      api.buildbucket.simulated_search_results(
          builds, 'Check the previous LKGM CL generation.buildbucket.search'),
  )

  builds = [
      build_pb2.Build(
          end_time=timestamp_pb2.Timestamp(seconds=SIMULATED_CURRENT_TIME -
                                           5 * 60 * 60),
          output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
      ),
  ]
  yield api.test(
      'basic2',
      api.time.seed(SIMULATED_CURRENT_TIME),
      api.buildbucket.simulated_search_results(
          builds, 'Check the previous LKGM CL generation.buildbucket.search'),
  )

  yield api.test(
      'basic3',
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(
          False, current_time=SIMULATED_CURRENT_TIME),
  )

  yield api.test(
      'basic4',
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(False),
  )

  builds = []
  yield api.test(
      'no-previous-generated-uprev-cl',
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(True),
  )
