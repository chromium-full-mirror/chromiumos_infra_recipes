# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that generates artifacts using HW Test results.

All builders run against the same source tree.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_plan',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_proctor',
    'failures',
    'naming',
    'orch_menu',
    'skylab',
    'test_util',
]

from google.protobuf import json_format

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipes.chromeos.build_target import BuildTargetProperties

PROPERTIES = OrchestratorProperties

# TODO(crbug/1053703): refactor this along with orchestrator.py
# Most of this builder will be greatly simplified as part of refactoring
# orchestrator.py into a menu module.  Any functions that look similar to those
# in orchestrator.py are expected migrate to a recipe module.


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties, config)


def DoRunSteps(api, properties, config):
  # Update the start ref to indicate we've begun processing the snapshot.
  api.orch_menu.push_manifest_refs(properties.update_manifest_refs.start)
  api.orch_menu.assert_changes_submittable()

  snapshot = api.orch_menu.gitiles_commit
  gerrit_changes = api.orch_menu.gerrit_changes

  # This orchestrator ignores the config, using enable_history=True
  if gerrit_changes:
    api.orch_menu.wait_for_inflight_orchestrator()

  completed_builds = api.orch_menu.plan_and_run_children(enable_history=True)

  # From here all builds should have been collected: move to checking results.
  with api.step.nest('check build results') as presentation:
    for build in completed_builds:
      if build.status in (common_pb2.STARTED, common_pb2.SCHEDULED):
        presentation.text = 'some builds are running/pending'
    relevant_builds = []
    for build in completed_builds:
      # Assume relevant if the child doesn't have the relevant_build prop.
      if ('relevant_build' not in build.output.properties or
          build.output.properties['relevant_build']):
        relevant_builds.append(build.builder.builder)
    presentation.logs['relevant_builds'] = \
        sorted(relevant_builds or ['no relevant builds'])
    failures = api.failures.get_build_failures(completed_builds)

  # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
  # non-critical. Snapshot builds are always scheduled without the critical bit
  # set to `NO` so this is also the only place that we will discover that.
  with api.step.nest('non-critical build check') as presentation:
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  fatal_failures = [f for f in failures if f.fatal == True]

  # If this is a dry run, check that the builds passed and quit.
  # TODO(crbug/1071440): Because the HW Tests have production side effects, we
  # need to not run them for dryruns at this time.
  if not properties.enable_tests_on_dry_runs and api.cq.state == api.cq.DRY:
    return api.failures.aggregate_failures(failures)

  # Otherwise, run tests for builds that weren't build failures and that
  # still exist as builders.
  need_tests_builds = [
      b for b in completed_builds if b.status == common_pb2.SUCCESS and
      child_builder_configs.get(b.builder.builder)
  ]

  test_failures = api.cros_test_proctor.run_proctor(need_tests_builds, snapshot,
                                                    gerrit_changes, True)
  failures.extend(test_failures)

  # Create InputArtifactInfo for the CHROME_DEBUG_BINARY from the creating
  # builder.
  art_property = lambda b: b.output.properties['artifacts']
  locs = list(
      set('{}/{}'.format(
          art_property(b)['gs_bucket'],
          art_property(b)['gs_path'])
          for b in need_tests_builds
          if art_property(b)['gs_bucket']))
  input_artifacts = [
      dict(artifact_types=[ArtifactsByService.Toolchain.CHROME_DEBUG_BINARY],
           gs_locations=locs)
  ]

  # Schedule and wait for any process_child builder.
  if not fatal_failures and properties.process_child:
    processed = [
        api.orch_menu.schedule_wait_build(
            properties.process_child, await_completion=True,
            properties=dict(input_artifacts=input_artifacts),
            step_name='run {}'.format(properties.process_child),
            timeout_sec=4 * 60 * 60)
    ]

    completed_builds.extend(processed)
    # Update the failure variables.
    process_failures = api.failures.get_build_failures(processed)
    failures.extend(process_failures)
    fatal_failures.extend([f for f in process_failures if f.fatal == True])

  # Launch any specified follow on orchestrator.
  if not fatal_failures and config.orchestrator.follow_on_orchestrator.name:
    completed_builds.append(
        api.orch_menu.schedule_wait_build(
            config.orchestrator.follow_on_orchestrator.name,
            config.orchestrator.follow_on_orchestrator.await_completion))

  with api.step.nest('clean up orchestrator') as presentation:
    # Recheck the BuilderConfigs at HEAD, one last time, to see if any failed
    # builders are now noncritical.
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  return api.failures.aggregate_failures(failures)


def GenTests(api):

  def test_orchestrator(**kwargs):
    """Generate a test build proto for the postsubmit orchestrator."""
    return api.test_util.test_orchestrator(**kwargs).build

  def vm_test_build(name):
    # The only things we care about are output.properties.name and status.
    return json_format.ParseDict(
        dict(
            output=dict(properties=dict(name=name)), status=common_pb2.SUCCESS),
        build_pb2.Build())

  vm_tests = [vm_test_build('vm-test')]

  moblab_vm_tests = [vm_test_build('moblab-vm-test')]

  cros_test_platforms = [
      build_pb2.Build(id=1234, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
      build_pb2.Build(id=4321, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
  ]
  ctp_response1 = rpc_pb2.BatchResponse(
      responses=[dict(schedule_build=cros_test_platforms[0])])
  ctp_response2 = rpc_pb2.BatchResponse(
      responses=[dict(schedule_build=cros_test_platforms[1])])

  hw_tests = [
      api.skylab.test_with_execute_response_json(id=1234),
      api.skylab.test_with_execute_response_json(id=4321),
  ]

  builds = [
      api.test_util.test_child_build(
          'amd64-generic', cq=True, build_id=8922054662172514000,
          status='SUCCESS', output_properties=dict(
              build_cost=10.0, artifacts=dict(
                  files_by_artifact={
                      "CHROME_DEBUG_BINARY": ["chrome.debug.bz2"]
                  }, gs_bucket="chromeos-image-archive",
                  gs_path="GS_PATH/DIR"))).message,
      api.test_util.test_child_build(
          'arm-generic', cq=True, build_id=8922054662172514001,
          status='STARTED', output_properties=dict(
              artifacts=dict(
                  files_by_artifact={
                      "CHROME_DEBUG_BINARY": ["chrome.debug.bz2"]
                  }, gs_bucket="chromeos-image-archive",
                  gs_path="GS_PATH/DIR"))).message,
      api.test_util.test_child_build(
          'atlas', cq=True, build_id=8922054662172514002, start_time=1562475245,
          status='SUCCESS', output_properties=dict(
              artifacts=dict(
                  files_by_artifact={
                      "CHROME_DEBUG_BINARY": ["chrome.debug.bz2"]
                  }, gs_bucket="chromeos-image-archive",
                  gs_path="GS_PATH/DIR")), revision=None).message,
  ]

  # we have three here to properly exercise "prioritize_builds"
  followon_resp1 = rpc_pb2.BatchResponse(responses=[
      dict(
          schedule_build=api.test_util.test_orchestrator(
              build_id=5555, bucket='toolchain',
              builder='orderfile-verify-orchestrator',
              status='SUCCESS').message)
  ])

  process_resp1 = rpc_pb2.BatchResponse(responses=[
      dict(
          schedule_build=api.test_util.test_orchestrator(
              build_id=5555, bucket='toolchain',
              builder='afdo-process-toolchain', status='SUCCESS').message)
  ])

  yield api.test(
      'basic',
      test_orchestrator(),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'join_if_inflight_orchs',
      test_orchestrator(cq=True),
      api.buildbucket.simulated_search_results(
          builds, step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          builds, 'find inflight orchestrator.waiting for existing runs'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'runs_if_no_inflight_orchs',
      test_orchestrator(cq=True),
      api.buildbucket.simulated_search_results(
          [], step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test('dry_run', test_orchestrator(cq=True, dry_run=True))

  yield api.test(
      'quota_scheduler_override',
      test_orchestrator(
          cq=True, tags=api.cros_tags.tags(
              cq_cl_tag='pupr:chromeos-base/chromeos-chrome')),
      api.buildbucket.simulated_search_results(
          builds, 'run builds.get build history.'
          'get completed builds.get change build history.'
          'buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'orchestrator_with_process_child_and_followon',
      test_orchestrator(bucket='toolchain',
                        builder='orderfile-generate-orchestrator',
                        revision=None),
      api.properties(process_child='PROCESS'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
      api.buildbucket.simulated_schedule_output(
          process_resp1, 'run PROCESS.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          followon_resp1, 'run follow on orchestrator.buildbucket.schedule'),
  )
