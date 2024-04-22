# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for choosing snapshots with requested builders."""

from google.protobuf import json_format

from PB.chromiumos import builder_config as builder_config_pb2
from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStats

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/time',
    'build_plan',
    'cros_infra_config',
    'git_footers',
    'orch_menu',
    'test_util',
]


def RunSteps(api):
  test_child_specs = [
      builder_config_pb2.BuilderConfig.Orchestrator.ChildSpec(name=x)
      for x in api.properties.get('input_child_spec_names', [])
  ]
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  internal_snapshot = common_pb2.GitilesCommit()
  external_snapshot = common_pb2.GitilesCommit()

  with api.orch_menu.setup_orchestrator():
    _ = api.build_plan.get_build_plan(test_child_specs, enable_history=False,
                                      gerrit_changes=gerrit_changes,
                                      internal_snapshot=internal_snapshot,
                                      external_snapshot=external_snapshot)


def GenTests(api):
  TEST_SEED_TIME_SECONDS = 1613779827
  snapshot = api.test_util.test_orchestrator(
      build_id=111, revision='aaaa',
      start_time=TEST_SEED_TIME_SECONDS - (60 * 60 * 3), output_properties={
          'greenness':
              json_format.MessageToDict(
                  greenness_pb2.AggregateGreenness(
                      aggregate_build_metric=75, builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='target-1-snapshot', build_metric=100),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='target-2-snapshot', build_metric=100),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='target-3-snapshot', build_metric=100),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='target-4-snapshot', build_metric=0),
                      ]))
      }).message

  staging_snapshot = api.test_util.test_orchestrator(
      build_id=222, revision='bbbb',
      start_time=TEST_SEED_TIME_SECONDS - (60 * 60 * 3), output_properties={
          'greenness':
              json_format.MessageToDict(
                  greenness_pb2.AggregateGreenness(
                      aggregate_build_metric=66, builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='staging-target-a-snapshot',
                              build_metric=100),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='staging-target-b-snapshot',
                              build_metric=100),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='staging-target-c-snapshot',
                              build_metric=0),
                      ]))
      }).message

  # Mock builder configs.
  test_configs = builder_config_pb2.BuilderConfigs()
  critical_cq_child_builders = [
      'target-1-cq',
      'target-2-cq',
      'target-2-slim-cq',
      'target-3-cq',
      'target-4-cq',
      'target-5-cq',  # Target is not in snapshot.
      'staging-target-a-cq',
      'staging-target-b-cq',
      'staging-target-b-slim-cq',
  ]
  non_critical_cq_child_builders = [
      'target-6-cq',  # Target is not in snapshot.
  ]
  for b in critical_cq_child_builders:
    tc = test_configs.builder_configs.add()
    tc.id.name = b
    tc.general.critical.value = True
  for b in non_critical_cq_child_builders:
    tc = test_configs.builder_configs.add()
    tc.id.name = b
    tc.general.critical.value = False

  snap_orch = test_configs.builder_configs.add()
  snap_orch.id.name = 'snapshot-orchestrator'
  snap_orch.orchestrator.child_specs.add().name = 'target-1-snapshot'
  snap_orch.orchestrator.child_specs.add().name = 'target-2-snapshot'
  snap_orch.orchestrator.child_specs.add().name = 'target-3-snapshot'
  snap_orch.orchestrator.child_specs.add().name = 'target-4-snapshot'

  staging_snap_orch = test_configs.builder_configs.add()
  staging_snap_orch.id.name = 'staging-snapshot-orchestrator'
  staging_snap_orch.orchestrator.child_specs.add(
  ).name = 'staging-target-a-snapshot'
  staging_snap_orch.orchestrator.child_specs.add(
  ).name = 'staging-target-b-snapshot'
  staging_snap_orch.orchestrator.child_specs.add(
  ).name = 'staging-target-c-snapshot'

  def _step_test_data(staging=False, disable_exp=False):
    experiments = [] if disable_exp else [
        'chromeos.looks_for_green.targeted_lfg'
    ]
    ret = api.buildbucket.try_build(
        builder='staging-cq-orchestrator' if staging else 'cq-orchestrator',
        experiments=experiments)
    ret += api.time.seed(TEST_SEED_TIME_SECONDS)
    # Step data enabling LFG.
    ret += api.properties(
        **{
            '$chromeos/looks_for_green': {
                'enable_looks_for_green': True,
                'greenness_threshold': 75
            }
        })
    ret += api.git_footers.simulated_get_footers(
        [],
        'looks for green.check should look for green.check disallow looks for green'
    )
    ret += api.git_footers.simulated_get_footers(
        [],
        'looks for green.check should look for green.check if all Cq-Depend CLs are included'
    )
    # Step data searching for getting snapshots from buildbucket.
    ret += api.buildbucket.simulated_search_results(
        builds=[snapshot if not staging else staging_snapshot],
        step_name='looks for green.find green snapshot.buildbucket.search')
    # Step data overriding the builder configs.
    ret += api.cros_infra_config.override_builder_configs_test_data(
        test_configs,
        step_name='set up orchestrator.configure builder.cros_infra_config')
    return ret

  yield api.test(
      'all-cq-builders-in-snapshot-uses-subset-greenness',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          input_child_spec_names=['target-1-cq', 'target-2-slim-cq']),
      _step_test_data(),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(
                  status='STATUS_RAN_OLDER', lookback_hours=10,
                  suggested=LooksForGreenStats.SnapshotStats(
                      snap_orch_greenness=75,
                      requested_builders_greenness=100,
                      approx_snap_age_hours=3,
                      snap_orch_bbid=111,
                      snap_commit_sha='aaaa',
                  )))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'all-cq-builders-in-snapshot-but-experiment-not-enabled',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          input_child_spec_names=['target-1-cq', 'target-2-slim-cq']),
      _step_test_data(disable_exp=True),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(
                  status='STATUS_RAN_OLDER', lookback_hours=10,
                  suggested=LooksForGreenStats.SnapshotStats(
                      snap_orch_greenness=75,
                      approx_snap_age_hours=3,
                      snap_orch_bbid=111,
                      snap_commit_sha='aaaa',
                  )))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(input_child_spec_names=[
          'staging-target-a-cq', 'staging-target-b-slim-cq'
      ]),
      _step_test_data(staging=True),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(
                  status='STATUS_RAN_OLDER', lookback_hours=10,
                  suggested=LooksForGreenStats.SnapshotStats(
                      snap_orch_greenness=66,
                      requested_builders_greenness=100,
                      approx_snap_age_hours=3,
                      snap_orch_bbid=222,
                      snap_commit_sha='bbbb',
                  )))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-all-cq-builders-in-snapshot-uses-agg-green',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(input_child_spec_names=['target-1-cq', 'target-5-cq']),
      _step_test_data(),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(
                  status='STATUS_RAN_OLDER', lookback_hours=10,
                  suggested=LooksForGreenStats.SnapshotStats(
                      snap_orch_greenness=75,
                      approx_snap_age_hours=3,
                      snap_orch_bbid=111,
                      snap_commit_sha='aaaa',
                  )))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-build-not-in-snapshot-is-non-crit-uses-targeted',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(input_child_spec_names=['target-1-cq', 'target-6-cq']),
      _step_test_data(),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(
                  status='STATUS_RAN_OLDER', lookback_hours=10,
                  suggested=LooksForGreenStats.SnapshotStats(
                      snap_orch_greenness=75,
                      requested_builders_greenness=100,
                      approx_snap_age_hours=3,
                      snap_orch_bbid=111,
                      snap_commit_sha='aaaa',
                  )))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'snapshot-is-green-but-not-for-requested-builders-finds-none',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(input_child_spec_names=['target-1-cq', 'target-4-cq']),
      _step_test_data(),
      api.post_process(
          post_process.PropertyEquals, 'looks_for_green',
          json_format.MessageToDict(
              LooksForGreenStats(lookback_hours=10,
                                 status='STATUS_FOUND_NONE'))),
      api.post_process(post_process.DropExpectation),
  )
