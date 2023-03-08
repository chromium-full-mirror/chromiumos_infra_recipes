# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

import json
from typing import Callable, Dict

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.cros_relevance.cros_relevance import CrosRelevanceProperties
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
    'exonerate',
    'orch_menu',
    'signing',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  api.cros_try.check_try_version()
  api.checkpoint.register()
  with api.orch_menu.setup_orchestrator() as config:
    if config:
      DoRunSteps(api)

    is_release = api.orch_menu.is_release_orchestrator
    is_public = api.orch_menu.is_public_orchestrator

    return api.orch_menu.create_recipe_result(
        include_build_details=is_release or is_public,
        ignore_build_test_failures=is_release)


def DoRunSteps(api: RecipeApi):

  # Run the child builders.
  extra_child_props = {}

  # If the orchestrator was given a manifest to sync to, pass it on to the
  # children.
  if api.cros_source.sync_to_manifest:
    extra_child_props['$chromeos/cros_source'] = MessageToDict(
        CrosSourceProperties(sync_to_manifest=api.cros_source.sync_to_manifest))
  # If a release builder, need to pass information about the pinned manifest.
  elif api.orch_menu.is_release_orchestrator:
    extra_child_props['$chromeos/cros_source'] = MessageToDict(
        CrosSourceProperties(sync_to_manifest=api.cros_release.buildspec))
    if api.orch_menu.skip_paygen:
      extra_child_props['skip_paygen'] = True

  if api.orch_menu.is_postsubmit_orchestrator:
    extra_child_props['$chromeos/cros_relevance'] = MessageToDict(
        CrosRelevanceProperties(force_postsubmit_relevance=True))

  if api.orch_menu.chromium_src_ref_cl_tag:
    extra_child_props[
        '$chromeos/chrome'] = api.orch_menu.chrome_module_child_props()

  if api.cros_source.use_external_source_cache:
    if '$chromeos/cros_source' not in extra_child_props:
      extra_child_props['$chromeos/cros_source'] = {}
    extra_child_props['$chromeos/cros_source'][
        'use_external_source_cache'] = True

  if api.signing.ignore_already_exists_errors:
    extra_child_props['$chromeos/signing'] = {
        'ignore_already_exists_errors': True,
    }

  async_unit_tests_enabled = 'chromeos.build_cq.async_unit_tests' in api.buildbucket.build.input.experiments
  if api.orch_menu.is_cq_orchestrator and async_unit_tests_enabled:
    testable_builds = api.orch_menu.plan_and_wait_for_images()
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
        # Don't want to run tests on the public orchestrator, and unlike other
        # orchestrators without testing we can't run the test plan generator because
        # it requires access to internal repos.
        api.orch_menu.plan_and_run_tests(
            container_metadata=metadata,
            testable_builds=testable_builds,
            ignore_gerrit_changes=api.orch_menu.is_release_orchestrator,
            # If async unit tests are enabled, don't create the nested 'final
            # build collect' step, so that the 'check build results' step is
            # a top-level step.
            no_nest_final_build_collect=async_unit_tests_enabled,
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

  yield api.orch_menu.test('basic', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
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
              "$chromeos/cros_lkgm": {
                  "enable_lkgm": True,
                  "full_run": True,
                  "builder_threshold_percentage": 0,
              },
              "$chromeos/orch_menu":
                  OrchMenuProperties(skip_paygen=True,
                                     schedule_public_build=True),
              '$chromeos/signing': {
                  'ignore_already_exists_errors': True,
              }
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
      api.post_check(post_process.StatusSuccess),
      builder='release-main-orchestrator',
      with_history=True,
      collect_builds=data.builds,
      with_manifest_refs=True,
      bot_size='medium')

  yield api.orch_menu.test(
      'release-orchestrator-snapshot-experiment',
      data.ctp_normal,
      api.properties(
          **{
              "$chromeos/cros_lkgm": {
                  "enable_lkgm": True,
                  "full_run": True,
                  "builder_threshold_percentage": 0,
              },
              "$chromeos/orch_menu":
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
      api.post_check(post_process.StatusSuccess),
      builder='release-main-orchestrator',
      with_history=True,
      collect_builds=data.builds,
      with_manifest_refs=True,
      bot_size='medium',
      experiments=['chromeos.cros_infra_config.release_tot_builds_snapshot'])

  yield api.orch_menu.test(
      'public-orchestrator',
      api.properties(
          **{
              "$chromeos/cros_source":
                  CrosSourceProperties(
                      sync_to_manifest=ManifestLocation(
                          manifest_gs_path='gs://foo/bar.xml'),
                      use_external_source_cache=True)
          }), api.post_check(post_process.StatusSuccess),
      builder='public-main-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  # Needed to check `cros_source` instantiation in extra_child_props.
  yield api.orch_menu.test(
      'public-orchestrator-no-manifest',
      api.properties(
          **{
              "$chromeos/cros_source":
                  CrosSourceProperties(use_external_source_cache=True)
          }), api.post_check(post_process.StatusSuccess),
      builder='public-main-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  yield api.orch_menu.test(
      'factory-orchestrator', data.ctp_normal,
      api.properties(
          **{
              "$chromeos/cros_source":
                  CrosSourceProperties(
                      sync_to_manifest=ManifestLocation(
                          manifest_gs_path='gs://foo/bar.xml'),
                      use_external_source_cache=True)
          }), api.post_check(post_process.StatusSuccess),
      builder='factory-corsola-15197.B-orchestrator', with_history=True,
      collect_builds=data.builds, with_manifest_refs=True, bot_size='medium')

  yield api.orch_menu.test('bisecting-orchestrator', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           builder='bisecting-orchestrator')

  yield api.orch_menu.test('builds-with-history', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess), cq=True,
                           collect_builds=data.builds, with_history=True,
                           git_footers=[])

  yield api.orch_menu.test('joinable-existing-annealing-builds',
                           data.ctp_normal,
                           annealing_builds=data.annealing_builds,
                           collect_builds=data.builds, with_history=True,
                           with_manifest_refs=True)

  yield api.orch_menu.test(
      'chromium-src-ref-cq-cl-tag', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.buildbucket.ci_build(
          project='chromeos', bucket='postsubmit',
          builder='postsubmit-orchestrator',
          tags=api.cros_tags.tags(cq_cl_tag='chromium_src_ref:foo1234ref')),
      collect_builds=data.builds)

  find_inflight_name = 'find inflight orchestrator'
  wait_inflight_name = '%s.waiting for existing runs.wait' % find_inflight_name
  yield api.orch_menu.test(
      'join-if-inflight-orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[data.inflight_orchestrator],
      cq=True, with_history=True)

  yield api.orch_menu.test(
      'runs-if-no-inflight-orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, find_inflight_name),
      api.post_check(post_process.DoesNotRun,
                     wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[], cq=True, with_history=True)

  yield api.orch_menu.test('updates-refs', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_manifest_refs=True, collect_builds=data.builds)

  yield api.orch_menu.test(
      'does-not-update-refs', data.ctp_normal,
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun,
                     'update manifest-internal ref refs/heads/stable'),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/stable'),
      with_manifest_refs=True, max_build_failure_ratio=0.49,
      collect_builds=data.crit_fail)

  yield api.orch_menu.test(
      'missing-gitiles-commit', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'update manifest-internal ref refs/heads/postsubmit'),
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/stable'),
      collect_builds=data.builds, revision=None, with_manifest_refs=True)

  yield api.orch_menu.test('orchestrator-with-follow_on', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds,
                           follow_on_orch=data.follow_on_orchestrator,
                           bucket='toolchain',
                           builder='orderfile-generate-orchestrator')

  yield api.orch_menu.test('missing-gitiles-commit-with-defaults',
                           data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds, revision=None,
                           with_manifest_refs=True)

  yield api.orch_menu.test('missing-gitiles-commit-with-changes',
                           data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds, revision=None, cq=True,
                           with_history=True, git_footers=[])

  def verify_qs_account_pupr(check: Callable[[bool], bool],
                             steps: Dict[str, Step]) -> bool:
    data = json.loads(
        steps['run tests.schedule tests.schedule hardware tests.'
              'schedule skylab tests v2.buildbucket.schedule'].stdin)
    return check(data['requests'][0]['scheduleBuild']['properties']['requests']
                 ['htarget.hw.bvt-inline']['params']['scheduling']['qsAccount']
                 == u'pupr')

  yield api.orch_menu.test(
      'quota-scheduler-override', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(verify_qs_account_pupr), cq=True, with_history=True,
      tags=dict(cq_cl_tag='pupr:chromeos-base/lacros-ash-atomic'),
      git_footers=[], collect_builds=data.builds)

  yield api.orch_menu.test('retry-only-critical-builds', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess), cq=True,
                           with_history=True, git_footers=[],
                           collect_builds=data.non_crit_fail)

  yield api.orch_menu.test('critical-child-builder-fails', data.ctp_normal,
                           api.post_check(post_process.StatusAnyFailure),
                           with_manifest_refs=True,
                           collect_builds=data.crit_fail)

  yield api.orch_menu.test('critical-child-builder-fails-but-release',
                           data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           builder='release-main-orchestrator',
                           with_manifest_refs=True,
                           collect_builds=data.crit_fail)

  yield api.orch_menu.test('non-critical-child-builder-fails', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_manifest_refs=True,
                           collect_builds=data.non_crit_fail)

  yield api.orch_menu.test(
      'async-unit-test-experiment',
      data.ctp_normal,
      api.post_check(post_process.MustRun, 'run builds.schedule new builds'),
      api.post_check(post_process.MustRun,
                     'run builds.collect.buildbucket.get_multi'),
      api.post_check(post_process.MustRun, 'aggregating metadata'),
      api.post_check(post_process.MustRun, 'collect.get'),
      api.post_check(post_process.MustRun, 'check build results'),
      api.post_check(post_process.StatusSuccess),
      builder='cq-orchestrator',
      experiments=['chromeos.build_cq.async_unit_tests'],
  )
