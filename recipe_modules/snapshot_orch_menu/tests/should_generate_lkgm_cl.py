# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests `should_generate_lkgm_cl()` method in `snapshot_orch_menu` module.
"""
from datetime import datetime

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.snapshot_orch_menu.tests.should_generate_lkgm_cl import ShouldGenerateLkgmClProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/time',
    'failures',
    'snapshot_orch_menu',
    'test_util',
]

PROPERTIES = ShouldGenerateLkgmClProperties


def RunSteps(api, properties):
  # Set intial build status values.
  result = api.snapshot_orch_menu.should_generate_lkgm_cl(
      properties.current_lkgm_version)

  api.assertions.assertEqual(result, properties.expected_result)


def GenTests(api):
  SIMULATED_CURRENT_BUILD_START_TIME = 1717214400  # Sun Jun 01 2024 04:00:00 UTC
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties['lkgm'] = {
      'uprev_cl_generated': True,
      'uprev_dryrun': False,
      'version': '12345.0.0-12345'
  }

  BUILDER_METADATA = {
      'project': 'chromeos',
      'bucket': 'postsubmit',
      'builder': 'snapshot-orchestrator'
  }

  yield api.test(
      'basic',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=True,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.buildbucket.ci_build(
          start_time=datetime.utcfromtimestamp(
              SIMULATED_CURRENT_BUILD_START_TIME), **BUILDER_METADATA),
      api.buildbucket.simulated_search_results(
          [
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(**BUILDER_METADATA),
                  # Started 6 hours before the current build.
                  start_time=timestamp_pb2.Timestamp(
                      seconds=SIMULATED_CURRENT_BUILD_START_TIME - 6 * 60 * 60),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          'Check the previous LKGM CL generation.buildbucket.search'),
  )

  yield api.test(
      'not-old-enough',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=False,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.buildbucket.ci_build(
          start_time=datetime.utcfromtimestamp(
              SIMULATED_CURRENT_BUILD_START_TIME), **BUILDER_METADATA),
      api.buildbucket.simulated_search_results(
          [
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(**BUILDER_METADATA),
                  # Started 5 hours before the current build.
                  start_time=timestamp_pb2.Timestamp(
                      seconds=SIMULATED_CURRENT_BUILD_START_TIME - 5 * 60 * 60),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          'Check the previous LKGM CL generation.buildbucket.search'),
  )

  yield api.test(
      'same-lkgm-version',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=False,
              current_lkgm_version='12345.0.0-12345',
          )),
      api.buildbucket.ci_build(
          start_time=datetime.utcfromtimestamp(
              SIMULATED_CURRENT_BUILD_START_TIME), **BUILDER_METADATA),
      api.buildbucket.simulated_search_results(
          [
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(**BUILDER_METADATA),
                  # Started 5 hours before the current build.
                  start_time=timestamp_pb2.Timestamp(
                      seconds=SIMULATED_CURRENT_BUILD_START_TIME - 5 * 60 * 60),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          'Check the previous LKGM CL generation.buildbucket.search'),
  )

  yield api.test(
      'no-previous-builds',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=False,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.buildbucket.ci_build(
          start_time=datetime.utcfromtimestamp(
              SIMULATED_CURRENT_BUILD_START_TIME), **BUILDER_METADATA),
      api.buildbucket.simulated_search_results(
          [
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(**BUILDER_METADATA),
                  # Started 5 hours before the current build.
                  start_time=timestamp_pb2.Timestamp(
                      seconds=SIMULATED_CURRENT_BUILD_START_TIME - 5 * 60 * 60),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          'Check the previous LKGM CL generation.buildbucket.search'),
  )

  yield api.test(
      'set_should_generate_lkgm_cl_as_false_with_custom_current_time',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=False,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(
          False, current_build_start_time=SIMULATED_CURRENT_BUILD_START_TIME),
  )

  yield api.test(
      'set_should_generate_lkgm_cl_as_false',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=False,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(False),
  )

  yield api.test(
      'set_should_generate_lkgm_cl_as_true',
      api.properties(
          ShouldGenerateLkgmClProperties(
              expected_result=True,
              current_lkgm_version='12345.0.0-12346',
          )),
      api.snapshot_orch_menu.set_should_generate_lkgm_cl(True),
  )
