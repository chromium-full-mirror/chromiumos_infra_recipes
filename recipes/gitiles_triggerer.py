# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules jobs based on its triggers."""

from collections import namedtuple

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import GitilesTrigger
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import Trigger
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.gitiles_triggerer import GitilesTriggererProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'test_util',
]


PROPERTIES = GitilesTriggererProperties

Key = namedtuple('_Key', ['repo', 'ref', 'branch'])


def _make_key(trigger: Trigger) -> Key:
  """Create a key from the trigger."""
  return Key(trigger.repo, trigger.ref, trigger.ref.replace('refs/heads/', ''))


def _expand(item: str, key: Key):
  """Expand item based on the trigger."""
  return item.format(**key._asdict())


def RunSteps(api: RecipeApi,
             properties: GitilesTriggererProperties) -> result_pb2.RawResult:
  # Recipe_engine does a poor job of gathering errors if they occur before a
  # step is created.  We do this step first thing, so that any errors can be
  # reported as more than a contentless INFRA-FAIL.
  api.step.nest('set up')

  default_project = api.buildbucket.build.builder.project
  triggers = {}

  for trigger in api.scheduler.triggers:
    # Remember only the most recent trigger for each key.
    if trigger.HasField('gitiles'):
      triggers[_make_key(trigger.gitiles)] = trigger.gitiles

  with api.step.nest('sleep configured delay'):
    api.time.sleep(properties.delay_trigger_seconds)

  refs_triggered = []
  # Call emit_triggers once for each unique key in the dictionary.
  for key, value in triggers.items():
    refs_triggered.append(value.ref)
    # Only send one trigger: the last (most recent) one in the list.
    trigger = api.scheduler.GitilesTrigger(repo=value.repo, ref=value.ref,
                                           revision=value.revision,
                                           inherit_tags=False)
    project = _expand(properties.project, key) or default_project
    jobs = [_expand(x.name, key) for x in properties.jobs]
    api.scheduler.emit_trigger(trigger, project, jobs,
                               step_name='trigger {} jobs'.format(project))
  return result_pb2.RawResult(
      status=common_pb2.Status.SUCCESS,
      summary_markdown='Triggered jobs for refs:\n{}'.format('\n'.join(
          ['- {}'.format(ref) for ref in refs_triggered])))


def GenTests(api: RecipeTestApi):
  triggers = [
      Trigger(
          gitiles=GitilesTrigger(
              repo=('https://chromium.googlesource.com/'
                    'chromiumos/overlays/chromiumos-overlay'),
              ref='refs/heads/release-R86-13421.B',
              revision='5314cf02b0214ff33c982ef76003661a7718f1d1',
          ),
      ),
      Trigger(
          gitiles=GitilesTrigger(
              repo=('https://chromium.googlesource.com/'
                    'chromiumos/overlays/chromiumos-overlay'),
              ref='refs/heads/release-R86-13421.B',
              revision='589f2dd59777915e8e05cc0738724033e3ad26ff',
          ),
      ),
  ]

  # When there are triggers, we trigger things.
  yield api.test(
      'triggers',
      api.test_util.test_build(
          input_properties={
              '$recipe_engine/scheduler': {
                  'triggers': [MessageToDict(x) for x in triggers]
              }
          }).build,
      api.properties(
          GitilesTriggererProperties(
              jobs=[GitilesTriggererProperties.Job(name='{branch}-branch-job')],
              delay_trigger_seconds=60)),
      api.post_check(post_process.MustRun, 'trigger chromeos jobs'),
  )
