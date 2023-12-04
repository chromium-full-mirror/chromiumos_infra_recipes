# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.recipe_modules.chromeos.build_plan.build_plan import BuildPlanProperties
from PB.recipe_modules.chromeos.build_plan.examples.cq_build_plan import (
    CqBuildPlanProperties)
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process

from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'build_plan',
    'cros_history',
    'cros_infra_config',
    'cros_relevance',
    'gerrit',
    'git_footers',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CqBuildPlanProperties


def RunSteps(api, properties):
  child_specs = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder).orchestrator.child_specs
  completed_builds, new_requests = api.build_plan.get_build_plan(
      child_specs, True, api.cros_infra_config.gerrit_changes,
      common_pb2.GitilesCommit(), common_pb2.GitilesCommit())
  actual_completed_builds = [x.builder.builder for x in completed_builds]
  api.assertions.assertCountEqual(actual_completed_builds,
                                  properties.expected_completed_builds)
  actual_build_requests = [x.builder.builder for x in new_requests]
  api.assertions.assertCountEqual(actual_build_requests,
                                  properties.expected_build_requests)
  enabled_experiments = {
      exp: enabled
      for exp, enabled in new_requests[0].experiments.items()
      if enabled
  }
  api.assertions.assertEqual({x: True for x in properties.expected_experiments},
                             enabled_experiments)
  api.assertions.assertEqual(
      api.build_plan.additional_chrome_pupr_builders,
      properties.expected_additional_chrome_pupr_builders)


def GenTests(api):
  input_proto = api.build_plan.input_proto
  builds = [
      # Completed successfully.
      build_pb2.Build(id=8922054662172514000, builder={'builder': 'cave-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'cave')),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'amd64-generic-slim-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic-slim')),
      # Non-critical private failure.
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'coral-cq'},
                      status=common_pb2.FAILURE,
                      input=input_proto(None, 'coral')),
      # Non-critical public failure.
      build_pb2.Build(id=8922054662172514003,
                      builder={'builder': 'arm-generic-cq'},
                      status=common_pb2.FAILURE,
                      input=input_proto(None, 'arm-generic')),
      # Broken before private builder.
      build_pb2.Build(id=8922054662172514004,
                      builder={'builder': 'atlas-slim-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas-slim')),
      build_pb2.Build(id=8922054662172514005, builder={'builder': 'atlas-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas')),
      # Broken before public builder.
      build_pb2.Build(id=8922054662172514006,
                      builder={'builder': 'arm64-generic-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'arm64-generic'))
  ]

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    return api.buildbucket.try_build(project='chromeos', **kwargs)

  yield api.test(
      'basic',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'all-internal-changes',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(gerrit_changes=[
          common_pb2.GerritChange(
              host='chrome-internal-review.googlesource.com', project='p1',
              change=1235),
      ]),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'cave-cq',
          ],
          expected_completed_builds=[],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          [], 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          [], 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'force-relevant',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'eve-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers(['eve-cq'],
                                            'check force relevance'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'coral-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'force-relevant-non-default',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          builder='staging-cq-orchestrator'),
      api.properties(
          expected_build_requests=['atlas-cq', 'arm64-generic-cq', 'eve-cq'],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      # Neither fake-cq nor eve-cq are a part of staging-cq-orchestrator's
      # child_specs. We expect eve-cq to get scheduled and fake-cq to get
      # filtered out as it does not correspond to a valid builder.
      api.git_footers.simulated_get_footers(['eve-cq', 'fake-cq'],
                                            'check force relevance'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
      api.post_check(post_process.LogEquals, 'check force relevance',
                     'invalid builders', 'fake-cq'),
  )

  yield api.test(
      'force-rebuild-non-critical-builder',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'coral-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers(['coral-cq'],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'coral-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'forced-rebuilds-all',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'coral-cq',
              'arm-generic-cq',
              'cave-cq',
          ],
          expected_completed_builds=[],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers(['all'],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'coral-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'forced-rebuilds-test-failures',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'coral-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers(['test-failures'],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'coral-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_failed_tests(['coral-cq'])
      ], 'check disallow recycled builds.find matching builds.buildbucket.search'
                                              ),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'experiments',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['named-experiment-from-cq']),
      api.properties(
          expected_experiments=[
              'named-experiment-from-cq', 'named-exp-from-cl'
          ],
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.git_footers.simulated_get_footers(['named-exp-from-cl'],
                                            'filter builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  config_ref = 'refs/changes/33/433/1'
  yield api.test(
      'with-config',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          bucket='staging', builder='staging-cq-orchestrator'),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ], expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ], expected_additional_chrome_pupr_builders=[], **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(config_ref=config_ref),
          }),
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref=config_ref,
          binaryproto=False),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'slim-eligible',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_experiments=[],
          expected_build_requests=[
              'atlas-slim-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'amd64-generic-slim-cq',
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-slim-cq',
              'cave-slim-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'chrome-pupr-additional-builders',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.build_plan.add_chrome_pupr_builders']),
      api.properties(
          expected_build_requests=[
              'eve-cq',
              'amd64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_experiments=['chromeos.build_plan.add_chrome_pupr_builders'],
          expected_additional_chrome_pupr_builders=[
              'amd64-generic-cq',
          ],
      ),
      api.step_data(
          'filter additional chrome pupr builds.read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'filter additional chrome pupr builds', [
              GerritChange(host='chromium-review.googlesource.com',
                           change=123456)
          ], {
              123456: {
                  'project': 'chromiumos/overlays/chromiumos-overlay',
                  'branch': 'main',
                  'topic': 'chromeos-base/lacros-ash-atomic',
                  'files': {
                      'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild':
                          {},
                  }
              },
          }, iteration=1),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=['eve-cq'], skipped_builders=[
              'atlas-cq', 'arm-generic-cq', 'amd64-generic-cq',
              'amd64-generic-slim-cq'
          ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.post_check(post_process.LogContains,
                     'filter additional chrome pupr builds',
                     'additional builds',
                     ['amd64-generic-slim-cq already passed']),
  )

  yield api.test(
      'chrome-pupr-no-additional-builders',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.build_plan.add_chrome_pupr_builders']),
      api.properties(
          expected_build_requests=['eve-cq'],
          expected_experiments=['chromeos.build_plan.add_chrome_pupr_builders'],
      ),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=['eve-cq'],
          skipped_builders=['atlas-cq', 'arm-generic-cq', 'arm64-generic-cq']),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  output = build_pb2.Build.Output()
  output.properties['greenness'] = {'aggregateBuildMetric': 100}
  output.properties['commit'] = {'id': 'sampleSnapshotSHA'}
  # Choosing timestamps based on time module's default test data.
  test_start_timestamp = timestamp_pb2.Timestamp(seconds=1336972527)
  test_end_timestamp = timestamp_pb2.Timestamp(seconds=1336997427)
  yield api.test(
      'cq-looks-enabled',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.looks for green.check should look for green.check disallow looks for green'
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.looks for green.check should look for green.check if CL uses Cq-Depend'
      ),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True,
          }},
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-slim-cq',
              'cave-cq',
          ],
          expected_experiments=[],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.git_footers.simulated_get_footers([],
                                            'check disallow recycled builds'),
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'arm-generic-cq',
              'arm64-generic-cq',
              'atlas-cq',
              'cave-cq',
          ], skipped_builders=[]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, output=output,
                              start_time=test_start_timestamp,
                              end_time=test_end_timestamp)
          ],
          step_name='filter builds.looks for green.checking latest scored snapshot greenness.buildbucket.search'
      ),
  )

  yield api.test(
      'no-pruning',
      cq_orchestrator_build_with_gerrit_change(),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.post_check(post_process.DoesNotRun,
                     'check for projects outside manifest'),
      api.properties(
          **{
              '$chromeos/build_plan':
                  BuildPlanProperties(
                      disable_build_plan_pruning=True,
                  ),
          }),
      api.properties(
          expected_build_requests=[
              'amd64-generic-cq',
              'atlas-cq',
              'arm-generic-cq',
              'arm-generic-pointless-cq',
              'arm64-generic-cq',
              'coral-cq',
              'cave-cq',
              'eve-cq',
          ],
          expected_completed_builds=[],
          expected_additional_chrome_pupr_builders=[],
      ),
  )

  yield api.test(
      'basic-with-project-outside-manifest',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.step_data(
          'check for projects outside manifest.check if project non-existent-project exists.repo info',
          stderr=api.raw_io.output_text(
              'project non-existent-project not found')),
      cq_orchestrator_build_with_gerrit_change(gerrit_changes=[
          common_pb2.GerritChange(
              host='chrome-internal-review.googlesource.com',
              project='non-existent-project', change=1235),
      ]),
      api.post_check(post_process.StepFailure,
                     'check for projects outside manifest'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'basic-with-project-inside-manifest',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.step_data(
          'check for projects outside manifest.check if project existent-project exists.repo info',
          stderr=api.raw_io.output_text('')),
      cq_orchestrator_build_with_gerrit_change(gerrit_changes=[
          common_pb2.GerritChange(
              host='chrome-internal-review.googlesource.com',
              project='existent-project', change=1235),
      ]),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'cave-cq',
              'coral-cq',
              'eve-cq',
          ],
          expected_completed_builds=[],
          expected_additional_chrome_pupr_builders=[],
      ),
      api.post_check(post_process.StepSuccess,
                     'check for projects outside manifest'),
  )
