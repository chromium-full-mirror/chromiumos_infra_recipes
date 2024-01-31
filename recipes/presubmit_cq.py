# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Launches presubmit tests for CQ."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.presubmit_cq import PresubmitCqProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_tags',
    'failures',
    'naming',
    'test_util',
]


PROPERTIES = PresubmitCqProperties


def RunSteps(api: RecipeApi, properties: PresubmitCqProperties):
  commit = api.buildbucket.build.input.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes
  input_props = {}
  bucket = 'infra'

  force_fullcheckout = False
  if len(
      changes) == 1 and changes[0].project in properties.fullcheckout_projects:
    force_fullcheckout = True

  with api.step.nest('validate inputs') as presentation:
    if len(changes) == 1 and not force_fullcheckout:
      presentation.step_text = 'One CL, using Infra Presubmit'
      builder = 'Infra Presubmit'
      # Do not inherit our version tag for Infra Presubmit, use the builder
      # definition.
      exe_cipd_version = ''
      if properties.runhooks:
        input_props['runhooks'] = properties.runhooks
      if properties.timeout_s > 0:
        input_props['timeout_s'] = properties.timeout_s
    elif len(changes) == 0:
      presentation.step_text = 'No build'
      raise StepFailure('No changes present')
    else:
      if len(changes) == 1:
        presentation.step_text = (
            'One CL, project configured for infra-fullcheckout-presubmit')
      else:
        presentation.step_text = (
            'Multiple changes, using infra-fullcheckout-presubmit')
      builder = 'infra-fullcheckout-presubmit'
      exe_cipd_version = api.buildbucket.INHERIT

  with api.step.nest('run {}'.format(builder)) as presentation:
    child_props = api.cq.props_for_child_build
    child_props.update(api.cros_infra_config.props_for_child_build)
    child_props.update(input_props)

    tags = api.cros_tags.make_schedule_tags(commit)

    request = api.buildbucket.schedule_request(
        builder=builder, bucket=bucket, critical=True, tags=tags,
        properties=child_props, exe_cipd_version=exe_cipd_version,
        swarming_parent_run_id=api.swarming.task_id, inherit_buildsets=False)
    child = api.buildbucket.schedule([request])[0]
    presentation.links[builder] = api.buildbucket.build_url(build_id=child.id)

    try:
      output = api.buildbucket.collect_builds(
          [child.id], step_name='collect', timeout=60 * 60 * 2,
          url_title_fn=api.naming.get_build_title)[child.id]
    except StepFailure:
      # If the child builder takes more than the given timeout, collect_builds
      # will raise StepFailure. If the failure is due to other reasons, then
      # get_multi will raise the same StepFailure.
      output = api.buildbucket.get_multi(
          [child.id], step_name='get',
          url_title_fn=api.naming.get_build_title)[child.id]

  with api.step.nest('check results') as presentation:
    return api.failures.aggregate_failures(
        api.failures.get_build_results([output]))


def GenTests(api: RecipeTestApi):

  props = PresubmitCqProperties(runhooks=True, timeout_s=3)

  # This is the normal case
  yield api.test('normal-one-change', api.test_util.test_build(cq=True).build)

  yield api.test(
      'normal-one-change-and-props',
      api.test_util.test_build(cq=True, input_properties=props).build)

  yield api.test(
      'one-change-fullcheckout',
      api.properties(fullcheckout_projects=['chromeos/config-internal']),
      api.test_util.test_build(
          cq=True, gerrit_changes=[
              common_pb2.GerritChange(change=1234,
                                      project='chromeos/config-internal')
          ]).build,
      api.post_check(post_process.StepSuccess,
                     'run infra-fullcheckout-presubmit'))

  yield api.test(
      'normal-two-changes',
      api.test_util.test_build(
          cq=True, extra_changes=[common_pb2.GerritChange(change=1235)]).build)

  # LUCI CQ doesn't generally give us a gitiles_commit, but we support that.
  yield api.test(
      'commit_with_no_changes',
      api.test_util.test_build().build,
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'commit-with-one-change',
      api.test_util.test_build(
          extra_changes=[common_pb2.GerritChange(change=1234)]).build)

  yield api.test(
      'commit-with-two-changes',
      api.test_util.test_build(extra_changes=[
          common_pb2.GerritChange(change=1234),
          common_pb2.GerritChange(change=1235),
      ]).build)

  yield api.test('timeout',
                 api.test_util.test_build(cq=True).build,
                 api.step_data('run Infra Presubmit.collect.wait', retcode=1))
