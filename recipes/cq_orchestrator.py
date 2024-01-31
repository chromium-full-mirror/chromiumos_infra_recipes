# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules CQ verifiers."""

import json
import typing

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'build_menu',
    'cros_tags',
    'easy',
    'orch_menu',
]



def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  with api.orch_menu.setup_orchestrator():
    # Run the child builders.
    extra_child_props = {
        # Value is a callback function that should be executed after LFG
        # has chosen the snapshot.
        '$chromeos/metadata':
            lambda: {
                'sources_gitiles_commit_override':
                    json_format.MessageToDict(api.build_menu.
                                              resultdb_gitiles_commit)
            }
    }

    testable_builds = api.orch_menu.plan_and_wait_for_images(
        extra_child_props=extra_child_props)

    # Aggregate any metadata produced by the child builds into our own GS bucket
    metadata = api.orch_menu.aggregate_metadata(testable_builds)

    # Run any HW tests.
    api.orch_menu.plan_and_run_tests(
        container_metadata=metadata,
        testable_builds=testable_builds,
    )

    # Collect any remaining builders and report the overall result.
    return api.orch_menu.create_recipe_result(no_nest_final_build_collect=True)

def GenTests(api: RecipeTestApi):

  data = api.orch_menu.standard_test_data()

  collect_builds, collect_after_builds = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')

  def _cq_schedule_and_collect_builds_test_data(collect, collect_after):
    ret = api.buildbucket.simulated_search_results(
        collect + collect_after, 'clean up orchestrator.buildbucket.search')
    for build in collect + collect_after:
      ret += api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': build
          }]),
          'run builds.schedule new builds.{}'.format(build.builder.builder))
    ret += api.orch_menu.build_poller_step_data(builds=collect,
                                                parent_step_name='run builds')
    ret += api.buildbucket.simulated_collect_output(collect + collect_after,
                                                    'collect')
    return ret

  yield api.orch_menu.test(
      'basic',
      data.ctp_normal,
      api.post_check(post_process.MustRun, 'run builds.schedule new builds'),
      api.post_check(post_process.MustRun, 'aggregating metadata'),
      api.post_check(post_process.MustRun, 'collect.get'),
      api.post_check(post_process.MustRun, 'check build results'),
      api.orch_menu.build_poller_step_data(builds=data.builds,
                                           parent_step_name='run builds'),
      builder='cq-orchestrator',
  )

  yield api.orch_menu.test(
      'builds-with-history',
      _cq_schedule_and_collect_builds_test_data(collect_builds,
                                                collect_after_builds),
      data.ctp_normal, cq=True, with_history=True, git_footers=[])

  find_inflight_name = 'find inflight orchestrator'
  wait_inflight_name = '%s.waiting for existing runs.wait' % find_inflight_name
  yield api.orch_menu.test(
      'join-if-inflight-orchs',
      _cq_schedule_and_collect_builds_test_data(collect_builds,
                                                collect_after_builds),
      data.ctp_normal, api.post_check(post_process.MustRun,
                                      wait_inflight_name), git_footers=[],
      inflight_orch=[data.inflight_orchestrator], cq=True, with_history=True)

  yield api.orch_menu.test(
      'runs-if-no-inflight-orchs',
      _cq_schedule_and_collect_builds_test_data(collect_builds,
                                                collect_after_builds),
      data.ctp_normal, api.post_check(post_process.MustRun, find_inflight_name),
      api.post_check(post_process.DoesNotRun, wait_inflight_name),
      git_footers=[], inflight_orch=[], cq=True, with_history=True)

  def verify_qs_account_pupr(check: typing.Callable[[bool], bool],
                             steps: typing.Dict[str, Step]) -> bool:
    data = json.loads(
        steps['run tests.schedule tests.schedule hardware tests.'
              'schedule skylab tests v2.buildbucket.schedule'].stdin)
    return check(data['requests'][0]['scheduleBuild']['properties']['requests']
                 ['htarget.hw.bvt-inline']['params']['scheduling']['qsAccount']
                 == 'pupr')

  yield api.orch_menu.test(
      'quota-scheduler-override', data.ctp_normal,
      _cq_schedule_and_collect_builds_test_data(collect_builds,
                                                collect_after_builds),
      api.post_check(verify_qs_account_pupr), cq=True, with_history=True,
      tags={'cq_cl_tag': 'pupr:chromeos-base/lacros-ash-atomic'},
      git_footers=[])

  collect_builds_with_crit_failure, _ = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')
  for b in collect_builds_with_crit_failure:
    if b.builder.builder == 'amd64-generic-cq':
      b.status = common_pb2.FAILURE
  yield api.orch_menu.test(
      'critical-child-builder-fails',
      _cq_schedule_and_collect_builds_test_data(
          collect_builds_with_crit_failure, collect_after_builds),
      data.ctp_normal,
      api.post_process(
          post_process.SummaryMarkdown,
          '1 out of 7 builds failed\n\n- amd64-generic-cq: '
          '[build page](https://cr-buildbucket.appspot.com/build/8922054662172514000)'
      ),
      cq=True,
      status='FAILURE',
  )

  collect_builds_with_non_crit_failure, _ = api.orch_menu.orch_child_builds(
      'cq-orchestrator', '-cq')
  for b in collect_builds_with_non_crit_failure:
    if b.builder.builder == 'arm-generic-cq':
      b.status = common_pb2.FAILURE
  yield api.orch_menu.test(
      'non-critical-child-builder-fails',
      _cq_schedule_and_collect_builds_test_data(
          collect_builds_with_non_crit_failure, collect_after_builds),
      data.ctp_normal,
      api.post_process(post_process.SummaryMarkdown,
                       '1 non-critical build failed'),
      cq=True,
  )
