# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that triggers cros_test_platform runs.
"""

from google.protobuf import duration_pb2
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.test_platform.request import Request

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_test_platform',
    'skylab',
]

BOARD = 'octopus'
SANITY_TEST_SUITE = 'infra_qual'
TIMEOUT_SECONDS = 30 * 60  # 30 minutes


def RunSteps(api):
  # Send an always-passing suite request to generate a consistent signal for
  # the staging environment.
  test_unit = _construct_test_unit(api, BOARD, SANITY_TEST_SUITE)
  test = test_unit.hw_test_cfg.hw_test[0]
  timeout = duration_pb2.Duration(seconds=TIMEOUT_SECONDS)

  api.skylab.create_recipe(test, test_unit, timeout, name='trigger CTP builder',
                           async_suite_run=True)

  # Replay the last successful production CTP build in staging to
  # seed staging with real requests.
  with api.step.nest('replay prod CTP run'):
    _replay_last_successful_ctp_build_in_staging(api)


def _construct_test_unit(api, board, test_suite):
  last_successful_board_build = _get_last_successful_postsubmit_build(
      api, board)
  return HwTestUnit(
      common=TestUnitCommon(
          build_payload=BuildPayload(
              artifacts_gs_bucket='chromeos-image-archive',
              artifacts_gs_path=last_successful_board_build.output
              .properties['artifacts']['gs_path'])),
      hw_test_cfg=HwTestCfg(
          hw_test=[
              HwTestCfg.HwTest(
                  common=TestSuiteCommon(
                      display_name='%s.hw.%s' % (board, test_suite),
                      critical={'value': True}),
                  suite=test_suite,
                  skylab_board=board,
                  pool='DUT_POOL_QUOTA',
              ),
          ],
      ),
  )


def _get_last_successful_build(api, builder, bucket):
  successful_builds = api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': bucket,
              'builder': builder,
          }, status=bb_common.SUCCESS,
          include_experimental=False), limit=1, fields=['input', 'output'],
      step_name='find recent green %s build' % builder)

  if not successful_builds:
    raise api.step.StepFailure('No successful builds found for builder %s' %
                               builder)

  return successful_builds[0]


def _get_last_successful_postsubmit_build(api, board):
  postsubmit_builder = board + '-postsubmit'
  return _get_last_successful_build(api, postsubmit_builder, 'postsubmit')


def _replay_last_successful_ctp_build_in_staging(api):
  build = _get_last_successful_build(api, 'cros_test_platform', 'testplatform')

  reqs = MessageToDict(build.input.properties["requests"])
  bb_tags = {'parent_buildbucket_id': str(api.buildbucket.build.id)}
  api.skylab.schedule_ctp_requests(tagged_requests=reqs, bb_tags=bb_tags)


def GenTests(api):
  builder_output_properties = struct_pb2.Struct()
  builder_output_properties['artifacts'] = {
      'gs_path': 'octopus-postsubmit/R86-13420.0.0-36875-8871425273263211168',
  }
  green_postsubmit_builds = [
      build_pb2.Build(
          builder={
              'project': 'chromeos',
              'bucket': 'postsubmit',
              'builder': 'octopus-postsubmit',
          },
          status='SUCCESS',
          output={'properties': builder_output_properties},
      )
  ]

  ctp_input_properties = struct_pb2.Struct()
  ctp_input_properties['requests'] = {
      "gale_gale": {
          "params": {
              "decorations": {
                  "tags": [
                      "label-board:gale", "analytics_name:RLZ",
                      "label-model:gale", "build:gale-release/R89-13729.57.2",
                      "suite:rlz", "ctp-fwd-task-name:RLZ",
                      "label-pool:MANAGED_POOL_QUOTA"
                  ]
              },
              "hardwareAttributes": {
                  "model": "gale"
              },
              "metadata": {
                  "debugSymbolsArchiveUrl":
                      "gs://chromeos-image-archive/gale-release/R89-13729.57.2",
                  "testMetadataUrl":
                      "gs://chromeos-image-archive/gale-release/R89-13729.57.2"
              },
              "retry": {
                  "allow": True,
                  "max": 3
              },
              "scheduling": {
                  "managedPool": "MANAGED_POOL_QUOTA",
                  "qsAccount": "legacypool-suites"
              },
              "softwareAttributes": {
                  "buildTarget": {
                      "name": "gale"
                  }
              },
              "softwareDependencies": [{
                  "chromeosBuild": "gale-release/R89-13729.57.2"
              }],
              "time": {
                  "maximumDuration": "153000s"
              }
          },
          "testPlan": {
              "suite": [{
                  "name": "rlz"
              }]
          }
      }
  }
  green_ctp_builds = [
      build_pb2.Build(
          builder={
              'project': 'chromeos',
              'bucket': 'testplatform',
              'builder': 'cros_test_platform',
          },
          status='SUCCESS',
          input={'properties': ctp_input_properties},
      )
  ]

  yield api.test(
      'successful run',
      api.buildbucket.simulated_search_results(
          green_postsubmit_builds,
          step_name='find recent green octopus-postsubmit build'),
      api.buildbucket.simulated_search_results(
          green_ctp_builds,
          step_name='replay prod CTP run.find recent green cros_test_platform build'
      ),
  )

  yield api.test(
      'octopus build not found',
      api.buildbucket.simulated_search_results(
          [], step_name='find recent green octopus-postsubmit build'))
