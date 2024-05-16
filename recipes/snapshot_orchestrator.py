# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules snapshot/postsubmit child builders and watches for failures."""

from google.protobuf.json_format import MessageToDict

from PB.recipe_engine import result as result_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'orch_menu',
    'snapshot_orch_menu',
]



def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  with api.snapshot_orch_menu.setup_orchestrator() as config:
    if config:
      DoRunSteps(api)

    return api.snapshot_orch_menu.create_recipe_result()


def DoRunSteps(api: RecipeApi):

  # Run the child builders.
  extra_child_props = {}
  extra_child_props['$chromeos/metadata'] = {
      'sources_gitiles_commit_override':
          MessageToDict(api.build_menu.resultdb_gitiles_commit)
  }

  builds_status = api.snapshot_orch_menu.plan_and_run_children(
      extra_child_props=extra_child_props,
  )
  testable_builds = builds_status.testable_builds
  # Run any HW tests.
  api.snapshot_orch_menu.plan_and_run_tests(testable_builds=testable_builds)


def GenTests(api: RecipeTestApi):

  data = api.snapshot_orch_menu.standard_test_data()
  lfg_props = api.properties(
      **{'$chromeos/greenness': {
          'publish_property': True
      }})

  yield api.snapshot_orch_menu.test('basic', data.ctp_normal, lfg_props,
                                    with_history=True,
                                    collect_builds=data.builds,
                                    with_manifest_refs=True,
                                    builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test('critical-child-builder-fails',
                                    data.ctp_normal, lfg_props,
                                    with_manifest_refs=True,
                                    collect_builds=data.crit_fail,
                                    status='FAILURE',
                                    builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test('non-critical-child-builder-fails',
                                    data.ctp_normal, lfg_props,
                                    with_manifest_refs=True,
                                    collect_builds=data.non_crit_fail,
                                    builder='snapshot-orchestrator')

  yield api.snapshot_orch_menu.test(
      'missing-gitiles-commit',
      data.ctp_normal,
      lfg_props,
      api.post_check(post_process.MustRun,
                     'update manifest-internal ref refs/heads/postsubmit'),
      collect_builds=data.builds,
      revision=None,
      with_manifest_refs=True,
  )
