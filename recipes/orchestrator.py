# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

PYTHON_VERSION_COMPATIBILITY = 'PY2'

DEPS = [
    'cros_release',
    'cros_tags',
    'orch_menu',
    'recipe_engine/buildbucket',
]

from google.protobuf.json_format import MessageToDict

import json

from recipe_engine import post_process
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_relevance.cros_relevance import CrosRelevanceProperties


def RunSteps(api):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api)
    return api.orch_menu.create_recipe_result()


def DoRunSteps(api):

  # Run the child builders.
  extra_child_props = {}
  # If a release builder, need to pass information about the pinned manifest.
  if api.orch_menu.is_release_orchestrator:
    extra_child_props['$chromeos/cros_source'] = MessageToDict(
        CrosSourceProperties(sync_to_manifest=api.cros_release.releasespec))
  elif api.orch_menu.is_postsubmit_orchestrator:
    extra_child_props['commit_overlay_binhost'] = True
    extra_child_props['$chromeos/cros_relevance'] = MessageToDict(
        CrosRelevanceProperties(force_postsubmit_relevance=True))

  if api.orch_menu.is_bisecting_orchestrator:
    extra_child_props['$chromeos/cros_relevance'] = MessageToDict(
        CrosRelevanceProperties(force_postsubmit_relevance=True))

  if api.orch_menu.chromium_src_ref_cl_tag:
    extra_child_props[
        '$chromeos/chrome'] = api.orch_menu.chrome_module_child_props()

  builds_status = api.orch_menu.plan_and_run_children(
      extra_child_props=extra_child_props,
  )

  # Aggregate any metadata produced by the child builds into our own GS bucket
  metadata = api.orch_menu.aggregate_metadata(builds_status.completed_builds)

  # Run any HW tests.
  api.orch_menu.plan_and_run_tests(container_metadata=metadata)

  # Launch any specified follow on orchestrator.
  api.orch_menu.run_follow_on_orchestrator()


def GenTests(api):

  data = api.orch_menu.standard_test_data()

  yield api.orch_menu.test('basic', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_history=True, collect_builds=data.builds,
                           with_manifest_refs=True)

  yield api.orch_menu.test('release-orchestrator', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           builder='main-release-orchestrator',
                           with_history=True, collect_builds=data.builds,
                           with_manifest_refs=True, bot_size='medium')

  yield api.orch_menu.test('bisecting-orchestrator', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           builder='bisecting-orchestrator')

  yield api.orch_menu.test('builds_with_history', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess), cq=True,
                           collect_builds=data.builds, with_history=True,
                           git_footers=[])

  yield api.orch_menu.test('joinable_existing_annealing_builds',
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
      'join_if_inflight_orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[data.inflight_orchestrator],
      cq=True, with_history=True)

  yield api.orch_menu.test(
      'runs_if_no_inflight_orchs', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, find_inflight_name),
      api.post_check(post_process.DoesNotRun,
                     wait_inflight_name), git_footers=[],
      collect_builds=data.builds, inflight_orch=[], cq=True, with_history=True)

  yield api.orch_menu.test('updates_refs', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_manifest_refs=True, collect_builds=data.builds)

  yield api.orch_menu.test(
      'does_not_update_refs', data.ctp_normal,
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun,
                     'update manifest-internal ref refs/heads/stable'),
      api.post_check(post_process.DoesNotRun,
                     'update manifest ref refs/heads/stable'),
      with_manifest_refs=True, max_build_failure_ratio=0.49,
      collect_builds=data.crit_fail)

  yield api.orch_menu.test(
      'missing_gitiles_commit', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'update manifest-internal ref refs/heads/postsubmit'),
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/stable'),
      collect_builds=data.builds, revision=None, with_manifest_refs=True)

  yield api.orch_menu.test('orchestrator_with_follow_on', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds,
                           follow_on_orch=data.follow_on_orchestrator,
                           bucket='toolchain',
                           builder='orderfile-generate-orchestrator')

  yield api.orch_menu.test('missing_gitiles_commit_with_defaults',
                           data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds, revision=None,
                           with_manifest_refs=True)

  yield api.orch_menu.test('missing_gitiles_commit_with_changes',
                           data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           collect_builds=data.builds, revision=None, cq=True,
                           with_history=True, git_footers=[])

  def verify_qs_account_pupr(check, steps):
    data = json.loads(
        steps['run tests.schedule tests.schedule hardware tests.'
              'schedule skylab tests v2.buildbucket.schedule'].stdin)
    return check(data['requests'][0]['scheduleBuild']['properties']['requests']
                 ['htarget.hw.bvt-inline']['params']['scheduling']['qsAccount']
                 == u'pupr')

  yield api.orch_menu.test(
      'quota_scheduler_override', data.ctp_normal,
      api.post_check(post_process.StatusSuccess),
      api.post_check(verify_qs_account_pupr), cq=True, with_history=True,
      tags=dict(cq_cl_tag='pupr:chromeos-base/chromeos-chrome'), git_footers=[],
      collect_builds=data.builds)

  yield api.orch_menu.test('retry_only_critical_builds', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess), cq=True,
                           with_history=True, git_footers=[],
                           collect_builds=data.non_crit_fail)

  yield api.orch_menu.test('critical_child_builder_fails', data.ctp_normal,
                           api.post_check(post_process.StatusAnyFailure),
                           with_manifest_refs=True,
                           collect_builds=data.crit_fail)

  yield api.orch_menu.test('non-critical_child_builder_fails', data.ctp_normal,
                           api.post_check(post_process.StatusSuccess),
                           with_manifest_refs=True,
                           collect_builds=data.non_crit_fail)
