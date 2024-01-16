# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

import json
from typing import Callable
from typing import Dict

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.checkpoint import RetryStep
from PB.chromiumos.common import Channel
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'build_menu',
    'checkpoint',
    'cros_artifacts',
    'cros_lkgm',
    'cros_release',
    'cros_source',
    'cros_tags',
    'cros_try',
    'easy',
    'orch_menu',
    'signing',
    'skylab',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = OrchestratorProperties


def RunSteps(api: RecipeApi,
             properties: OrchestratorProperties) -> result_pb2.RawResult:
  api.cros_try.check_try_version()
  api.checkpoint.register()
  with api.orch_menu.setup_orchestrator() as config:
    if config:
      DoRunSteps(api)

    is_release = api.orch_menu.is_release_orchestrator
    is_public = api.orch_menu.is_public_orchestrator

    return api.orch_menu.create_recipe_result(
        include_build_details=is_release or is_public,
        ignore_build_test_failures=is_release and
        not properties.build_failures_fatal,
        no_nest_final_build_collect=api.orch_menu.is_cq_orchestrator)


def DoRunSteps(api: RecipeApi):

  # Run the child builders.
  extra_child_props = {}

  # If the orchestrator was given a manifest to sync to, pass it on to the
  # children.
  if api.cros_source.sync_to_manifest:
    extra_child_props['$chromeos/cros_source'] = MessageToDict(
        CrosSourceProperties(sync_to_manifest=api.cros_source.sync_to_manifest))
  # If a release or factory builder, need to pass information about the pinned manifest.
  elif api.orch_menu.is_release_orchestrator or api.orch_menu.is_factory_orchestrator:
    extra_child_props['$chromeos/cros_source'] = MessageToDict(
        CrosSourceProperties(sync_to_manifest=api.cros_release.buildspec))

  if api.orch_menu.is_release_orchestrator:
    if api.orch_menu.skip_paygen:
      extra_child_props['skip_paygen'] = True

  if api.cros_source.use_external_source_cache:
    if '$chromeos/cros_source' not in extra_child_props:
      extra_child_props['$chromeos/cros_source'] = {}
    extra_child_props['$chromeos/cros_source'][
        'use_external_source_cache'] = True

  if api.signing.ignore_already_exists_errors:
    extra_child_props['$chromeos/signing'] = {
        'ignore_already_exists_errors': True,
    }

  if api.orch_menu.is_release_orchestrator:
    api.cros_release.set_release_qs_account()
    extra_child_props['override_qs_account'] = api.skylab.qs_account

  if api.orch_menu.is_cq_orchestrator:
    extra_child_props['$chromeos/metadata'] = {
        'sources_gitiles_commit_override':
            MessageToDict(api.build_menu.resultdb_gitiles_commit)
    }
  if api.orch_menu.is_release_orchestrator and api.cros_release.resultdb_gitiles_commit:
    extra_child_props['$chromeos/metadata'] = {
        'sources_gitiles_commit_override':
            MessageToDict(api.cros_release.resultdb_gitiles_commit)
    }

  if api.orch_menu.is_cq_orchestrator:
    testable_builds = api.orch_menu.plan_and_wait_for_images(
        extra_child_props=extra_child_props)
    # Aggregate any metadata produced by the child builds into our own GS bucket
    metadata = api.orch_menu.aggregate_metadata(testable_builds)
  else:
    builds_status = api.orch_menu.plan_and_run_children(
        extra_child_props=extra_child_props,
    )
    # Aggregate any metadata produced by the child builds into our own GS bucket
    metadata = api.orch_menu.aggregate_metadata(builds_status.completed_builds)
    testable_builds = builds_status.testable_builds

  # Run any HW tests.
  if not api.orch_menu.is_public_orchestrator:
    with api.checkpoint.retry(RetryStep.LAUNCH_TESTS) as run_step:
      if run_step:
        # If we're a release orchestrator AND cq-active then we shouldn't run
        # tests, the release orch is being used as a CQ verifier.
        if not (api.orch_menu.is_release_orchestrator and api.cq.active):
          # Don't want to run tests on the public orchestrator, and unlike other
          # orchestrators without testing we can't run the test plan generator because
          # it requires access to internal repos.
          api.orch_menu.plan_and_run_tests(
              container_metadata=metadata,
              testable_builds=testable_builds,
              ignore_gerrit_changes=api.orch_menu.is_release_orchestrator,
          )

  if api.orch_menu.is_release_orchestrator and api.cros_lkgm.has_public_build:
    api.cros_lkgm.collect_public_build()

    # Publish main-release so SuSch can figure out what ToT is.
    # TODO(b/247451917): Remove when SuSch is gone.
    if api.cros_source.is_tot:
      gs_path = 'LATEST-staging' if api.build_menu.is_staging else 'main-release'
      api.cros_artifacts.publish_latest_files('chromeos-image-archive', gs_path)

    api.cros_lkgm.do_lkgm(api.orch_menu.builds_status.completed_builds,
                          use_branch=not api.cros_source.is_tot)

  # Launch any specified follow on orchestrator.
  api.orch_menu.run_follow_on_orchestrator()


def GenTests(api: RecipeTestApi):

  data = api.orch_menu.standard_test_data()

  def _cq_schedule_and_collect_builds_test_data():
    cq_collect, cq_collect_after = api.orch_menu.orch_child_builds(
        'cq-orchestrator', '-cq')
    ret = api.buildbucket.simulated_search_results(
        cq_collect + cq_collect_after,
        'clean up orchestrator.buildbucket.search')
    for build in cq_collect + cq_collect_after:
      ret += api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': build
          }]),
          'run builds.schedule new builds.{}'.format(build.builder.builder))
    ret += api.orch_menu.build_poller_step_data(builds=cq_collect,
                                                parent_step_name='run builds')
    ret += api.buildbucket.simulated_collect_output(
        cq_collect + cq_collect_after, 'collect')
    return ret

  yield api.orch_menu.test('basic', data.ctp_normal,
                           with_history=True, collect_builds=data.builds,
                           with_manifest_refs=True)

  def get_public_orch():
    output = build_pb2.Build.Output()
    child_build_ids = [str(8922054662172514001 + x) for x in range(3)]
    output.properties.update({'child_builds': child_build_ids})
    return build_pb2.Build(id=8922054662172514000, output=output,
                           status=common_pb2.SUCCESS)

  yield api.orch_menu.test(
      'release-orchestrator',
      data.ctp_normal,
      api.properties(
          **{
              '$chromeos/cros_lkgm': {
                  'enable_lkgm': True,
                  'full_run': True,
                  'builder_threshold_percentage': 0,
              },
              '$chromeos/orch_menu':
                  OrchMenuProperties(skip_paygen=True,
                                     schedule_public_build=True),
              '$chromeos/signing': {
                  'ignore_already_exists_errors': True,
              },
              '$chromeos/cros_release': {
                  'channels': [Channel.CHANNEL_STABLE],
                  'dynamic_qs_account': True,
              },
          }),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.schedule public build'),
      api.buildbucket.simulated_collect_output(
          [get_public_orch()], step_name='collect public orchestrator.collect'),
      # On ToT, shouldn't be getting branch.
      api.post_check(post_process.DoesNotRun, 'get chrome branch'),
      api.post_check(post_process.MustRun, 'call chrome_chromeos_lkgm'),
      api.post_check(post_process.StepCommandDoesNotContain,
                     'call chrome_chromeos_lkgm', ['--branch']),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.schedule public build'),
      api.post_check(post_process.MustRun, 'run tests'),
      api.post_check(post_process.LogDoesNotContain,
                     'run builds.schedule new builds.eve-release-main',
                     'request',
                     ['$chromeos/metadata', 'sources_gitiles_commit_override']),
      builder='release-main-orchestrator',
      with_history=True,
      collect_builds=data.builds,
      with_manifest_refs=True,
      sheriff_rotations=['chromeos'],
      bot_size='medium')

  yield api.orch_menu.test(
      'release-orchestrator-snapshot',
      data.ctp_normal,
      api.properties(
          **{
              '$chromeos/cros_lkgm': {
                  'enable_lkgm': True,
                  'full_run': True,
                  'builder_threshold_percentage': 0,
              },
              '$chromeos/orch_menu':
                  OrchMenuProperties(skip_paygen=True,
                                     schedule_public_build=True),
              '$chromeos/signing': {
                  'ignore_already_exists_errors': True,
              }
          }),
      api.buildbucket.simulated_collect_output(
          [get_public_orch()], step_name='collect public orchestrator.collect'),
      # On ToT, shouldn't be getting branch.
      api.post_check(post_process.DoesNotRun, 'get chrome branch'),
      api.post_check(post_process.MustRun, 'call chrome_chromeos_lkgm'),
      api.post_check(post_process.StepCommandDoesNotContain,
                     'call chrome_chromeos_lkgm', ['--branch']),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.schedule public build'),
      builder='release-main-orchestrator',
      with_history=True,
      collect_builds=data.builds,
      with_manifest_refs=True,
      bot_size='medium')

  yield api.orch_menu.test('release-orchestrator-cq',
                           api.post_check(post_process.DoesNotRun, 'run_tests'),
                           api.cq(run_mode=api.cq.FULL_RUN),
                           api.post_process(post_process.DropExpectation),
                           builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'public-orchestrator',
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      sync_to_manifest=ManifestLocation(
                          manifest_gs_path='gs://foo/bar.xml'),
                      use_external_source_cache=True)
          }), builder='public-main-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  # Needed to check `cros_source` instantiation in extra_child_props.
  yield api.orch_menu.test(
      'public-orchestrator-no-manifest',
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(use_external_source_cache=True)
          }), builder='public-main-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  yield api.orch_menu.test(
      'factory-orchestrator', data.ctp_normal,
      api.properties(
          **{
              '$chromeos/cros_source':
                  CrosSourceProperties(
                      sync_to_manifest=ManifestLocation(
                          manifest_gs_path='gs://foo/bar.xml'),
                      use_external_source_cache=True)
          }), builder='factory-corsola-15197.B-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  yield api.orch_menu.test('builds-with-history',
                           _cq_schedule_and_collect_builds_test_data(),
                           data.ctp_normal, cq=True, with_history=True,
                           git_footers=[])


  find_inflight_name = 'find inflight orchestrator'
  wait_inflight_name = '%s.waiting for existing runs.wait' % find_inflight_name
  yield api.orch_menu.test(
      'join-if-inflight-orchs',
      _cq_schedule_and_collect_builds_test_data(), data.ctp_normal,
      api.post_check(post_process.MustRun, wait_inflight_name), git_footers=[],
      inflight_orch=[data.inflight_orchestrator], cq=True, with_history=True)

  yield api.orch_menu.test(
      'runs-if-no-inflight-orchs', _cq_schedule_and_collect_builds_test_data(),
      data.ctp_normal, api.post_check(post_process.MustRun, find_inflight_name),
      api.post_check(post_process.DoesNotRun, wait_inflight_name),
      git_footers=[], inflight_orch=[], cq=True, with_history=True)

  yield api.orch_menu.test('orchestrator-with-follow_on', data.ctp_normal,
                           collect_builds=data.builds,
                           follow_on_orch=data.follow_on_orchestrator,
                           bucket='toolchain',
                           builder='artifact-generate-orchestrator')

  yield api.orch_menu.test('missing-gitiles-commit-with-defaults',
                           data.ctp_normal,
                           collect_builds=data.builds, revision=None,
                           with_manifest_refs=True)

  yield api.orch_menu.test('missing-gitiles-commit-with-changes',
                           _cq_schedule_and_collect_builds_test_data(),
                           data.ctp_normal, revision=None, cq=True,
                           with_history=True, git_footers=[])

  def verify_qs_account_pupr(check: Callable[[bool], bool],
                             steps: Dict[str, Step]) -> bool:
    data = json.loads(
        steps['run tests.schedule tests.schedule hardware tests.'
              'schedule skylab tests v2.buildbucket.schedule'].stdin)
    return check(data['requests'][0]['scheduleBuild']['properties']['requests']
                 ['htarget.hw.bvt-inline']['params']['scheduling']['qsAccount']
                 == 'pupr')

  yield api.orch_menu.test(
      'quota-scheduler-override', data.ctp_normal,
      _cq_schedule_and_collect_builds_test_data(),
      api.post_check(verify_qs_account_pupr), cq=True, with_history=True,
      tags={'cq_cl_tag': 'pupr:chromeos-base/lacros-ash-atomic'},
      git_footers=[])


  yield api.orch_menu.test(
      'critical-child-builder-fails',
      data.ctp_normal,
      with_manifest_refs=True,
      collect_builds=data.crit_fail,
      status='FAILURE',
  )

  yield api.orch_menu.test('critical-child-builder-fails-but-release',
                           data.ctp_normal,
                           builder='release-main-orchestrator',
                           with_manifest_refs=True,
                           collect_builds=data.crit_fail)

  yield api.orch_menu.test(
      'critical-child-builder-fails-but-release-override',
      api.properties(**{
          'build_failures_fatal': True,
      }),
      data.ctp_normal,
      builder='release-main-orchestrator',
      with_manifest_refs=True,
      collect_builds=data.crit_fail,
      status='FAILURE',
  )

  yield api.orch_menu.test('non-critical-child-builder-fails', data.ctp_normal,
                           with_manifest_refs=True,
                           collect_builds=data.non_crit_fail)

  yield api.orch_menu.test(
      'cq-orchestrator',
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
      'release-commit-buildspec-upload-sources',
      api.properties(**{
          '$chromeos/cros_release': {
              'commit_buildspec_as_snapshot': True,
          },
      }),
      # ToT should not set an override commit.
      api.post_check(post_process.LogDoesNotContain,
                     'run builds.schedule new builds.eve-release-main',
                     'request',
                     ['$chromeos/metadata', 'sources_gitiles_commit_override']),
      builder='release-main-orchestrator',
  )

  yield api.orch_menu.test(
      'release-branch-commit-buildspec-upload-sources',
      api.properties(**{
          '$chromeos/cros_release': {
              'commit_buildspec_as_snapshot': True,
          },
      }),
      api.post_check(
          post_process.LogContains,
          'run builds.schedule new builds.kukui-release-R111-12345.B',
          'request', ['$chromeos/metadata', 'sources_gitiles_commit_override']),
      builder='release-R111-12345.B-orchestrator',
  )
