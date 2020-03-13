# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Launches presubmit tests for CQ."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

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
]

from PB.recipes.chromeos.presubmit_cq import PresubmitCqProperties
from PB.recipes.chromeos.presubmit_tests import PresubmitTestsProperties
from PB.recipe_modules.depot_tools.presubmit.properties import (
    InputProperties as InfraPresubmitProperties)

PROPERTIES = PresubmitCqProperties


def RunSteps(api, properties):
  commit = api.buildbucket.build.input.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  with api.step.nest('validate inputs') as presentation:
    if len(changes) == 1:
      presentation.step_text = 'One CL, using Infra Presubmit'
      bucket = 'infra'
      builder = 'Infra Presubmit'
      input_props = dict(runhooks=properties.runhooks,
                         timeout_s=properties.timeout_sec)
    elif len(changes) > 1:
      presentation.step_text = 'Multiple changes, using fullcheckout-presubmit'
      bucket = 'cq'
      builder = 'fullcheckout-presubmit'
      input_props = {}
    else:
      presentation.step_text = 'No build'
      raise api.step.StepFailure('No changes present')

  with api.step.nest('run {}'.format(builder)) as presentation:
    child_props = api.cq.props_for_child_build
    child_props.update(api.cros_infra_config.props_for_child_build)
    child_props.update(input_props)

    tags = api.cros_tags.make_schedule_tags(commit)

    request = api.buildbucket.schedule_request(
        builder=builder, bucket=bucket, critical=True, tags=tags,
        properties=child_props, swarming_parent_run_id=api.swarming.task_id)
    child = api.buildbucket.schedule([request])[0]
    presentation.links[api.naming.get_build_title(child)] = (
        api.buildbucket.build_url(build_id=child.id))

    try:
      output = api.buildbucket.collect_builds(
          [child.id], step_name='collect', timeout=60 * 60 * 2,
          url_title_fn=api.naming.get_build_title)[child.id]
    except api.step.StepFailure:  #pragma: no cover
      # If the child builder takes more than the given timeout, collect_builds
      # will raise StepFailure. If the failure is due to other reasons, then
      # get_multi will raise the same StepFailure.
      output = api.buildbucket.get_multi(
          [child.id], step_name='get',
          url_title_fn=api.naming.get_build_title)[child.id]

  with api.step.nest('check results') as presentation:
    return api.failures.aggregate_failures(
        api.failures.get_build_failures([output]))


def GenTests(api):

  def make_build(commit=None, changes=None):
    """Return a build.

    Args:
      commit (str): SHA1 hash for gitiles_commit.  Default: None.
      changes (list[GerritChange]): list of gerrit changes to apply.

    Returns:
      recipe_test_api.TestData object.
    """
    msg = api.buildbucket.ci_build_message(project='chromeos', bucket='infra',
                                           builder='presubmit-cq',
                                           revision=commit)
    if not commit:
      msg.input.gitiles_commit.Clear()
    if changes:
      msg.input.gerrit_changes.extend(changes)
    return api.buildbucket.build(msg)

  # This is the normal case
  yield (api.test('normal_one_change') +  #
         make_build(changes=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('normal_two_changes') +  #
         make_build(changes=[
             common_pb2.GerritChange(change=1234),
             common_pb2.GerritChange(change=1235),
         ]))

  # LUCI CQ doesn't generally give us a gitiles_commit, but we support that.
  yield (api.test('commit_with_no_changes') +  #
         make_build(commit='SHA'))

  yield (
      api.test('commit_with_one_change') +  #
      make_build(commit='SHA', changes=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('commit_with_two_changes') +  #
         make_build(
             commit='SHA', changes=[
                 common_pb2.GerritChange(change=1234),
                 common_pb2.GerritChange(change=1235),
             ]))
