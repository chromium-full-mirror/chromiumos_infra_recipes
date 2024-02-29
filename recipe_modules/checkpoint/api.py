# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for Checkpoints which enables partially retriable (release) builds."""

import json
from contextlib import contextmanager
from typing import List

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.checkpoint.checkpoint import CheckpointProperties

STEP_CASCADES = {
    # Orchestrator steps
    RetryStep.CREATE_BUILDSPEC: [RetryStep.RUN_CHILDREN],
    RetryStep.RUN_CHILDREN: [RetryStep.LAUNCH_TESTS],
    # RUN_CHILDREN is the "super" step of RUN_FAILED_CHILDREN, need to include
    # both if RUN_FAILED_CHILDREN is set.
    RetryStep.RUN_FAILED_CHILDREN: [
        RetryStep.RUN_CHILDREN, RetryStep.LAUNCH_TESTS
    ],

    # Child builder steps
    RetryStep.STAGE_ARTIFACTS: [RetryStep.PUSH_IMAGES],
    RetryStep.PUSH_IMAGES: [RetryStep.DEBUG_SYMBOLS, RetryStep.COLLECT_SIGNING],
    RetryStep.DEBUG_SYMBOLS: [RetryStep.COLLECT_SIGNING],
    RetryStep.COLLECT_SIGNING: [RetryStep.PAYGEN],

    # Paygen steps
    RetryStep.UPLOAD_PAYLOAD: [RetryStep.TEST_PAYLOAD],
}

ORIGINAL_BUILD_PROPERTIES = [
    # Of the form (recipe, step, filter on inclusion, property name)
    ('orchestrator', RetryStep.CREATE_BUILDSPEC, False, 'buildspec_gs_uri'),
    ('orchestrator', RetryStep.RUN_CHILDREN, False, 'child_builds'),
    ('orchestrator', RetryStep.RUN_FAILED_CHILDREN, True, 'child_builds'),
    ('build_release', RetryStep.STAGE_ARTIFACTS, False, 'artifact_link'),
    ('build_release', RetryStep.PUSH_IMAGES, False,
     'signing_instructions_uris'),
    # We want the previous build_report_uri regardless of where it failed.
    ('build_release', None, False, 'build_report_uri'),
]

STATUS_STARTED = 'STARTED'
STATUS_SUCCESS = 'SUCCESS'
STATUS_SKIPPED = 'SKIPPED'
STATUS_FAILED = 'FAILED'


class CheckpointApi(recipe_api.RecipeApi):
  """A module for managing release build checkpoints.

  See go/release-checkpoints-dd for context.
  """

  # TODO(b/262388770): Improve documentaton here, and link to a dev guide.
  def __init__(self, properties: CheckpointProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._retry_run = properties.retry
    self._retry_summary = {}
    self._do_retry_summary = properties.force_retry_summary or properties.retry
    self._original_build_bbid = None

    # If CREATE_BUILDSPEC is included we're just doing a full release build
    # so go ahead and turn off retry mode.
    if RetryStep.CREATE_BUILDSPEC in properties.exec_steps.steps:
      self._retry_run = False
      return

    self._original_build_bbid = properties.original_build_bbid
    if self._original_build_bbid:
      self._original_build_bbid = int(self._original_build_bbid)
    self._original_build = None

    # Do step cascades.
    self._run_steps = self.cascade(properties.exec_steps.steps)
    self._builder_run_steps = {
        builder: self.cascade(steps.steps)
        for builder, steps in properties.builder_exec_steps.items()
    }

    # Output properties from the previous builds.
    for _, _, _, prop in ORIGINAL_BUILD_PROPERTIES:
      setattr(self, prop, None)
    self.child_builder_data = {}
    self._builder_children = {}

  def is_retry(self) -> bool:
    """Return whether the build is a retry build."""
    return self._retry_run

  @property
  def original_build_bbid(self) -> int:
    """Return the BBID of the original build as set in input properties."""
    return self._original_build_bbid

  def is_run_step(self, step: 'RetryStep'):
    """Return whether the step will be run in this retry."""
    # RUN_FAILED_CHILDREN is not a step that is normally run, so we shouldn't
    # return true if we're not a retry.
    if step == RetryStep.RUN_FAILED_CHILDREN:
      return self._retry_run and step in self._run_steps
    return not self._retry_run or step in self._run_steps

  def builder_children(self) -> List[int]:
    """Get the BBIDs of the child builders that are image builders."""
    return list(self._builder_children.keys())

  def successful_builder_children_bbids(self) -> List[int]:
    """Get the BBIDs of the child builders that were successful."""
    child_builds = []
    for bbid, build in self._builder_children.items():
      if build.status == common_pb2.SUCCESS:
        child_builds.append(bbid)
    return child_builds

  def failed_builder_children(self) -> List[build_pb2.Build]:
    """Returns the list of child builders that failed.

    Returns:
      Names of child builders that failed, e.g. eve-release-main.
    """
    failed_children = []
    for _, build in self._builder_children.items():
      # TODO(b/262388770): Handle still-running builds?
      if build.status != common_pb2.SUCCESS:
        failed_children.append(build)
    return failed_children

  def builder_retry_props(self, builder: str) -> dict:
    """Return the `checkpoint` module properties to set for the child builder."""
    original_build_bbid = None
    for bbid, build in self.child_builder_data.items():
      if build.builder.builder == builder:
        original_build_bbid = bbid
        break
    # If we have no build to retry from, launch a non-retry build.
    if not original_build_bbid:
      return None
    return {
        'retry': True,
        'original_build_bbid': str(original_build_bbid),
        # Default to the generic exec_steps.
        'exec_steps': {
            'steps': self._builder_run_steps.get(builder, self._run_steps)
        }
    }

  @staticmethod
  def cascade(requested_steps: List['RetryStep']) -> List['RetryStep']:
    """Process step cascades for the requested steps.

    Returns:
      All the steps that are meant to be run.
    """
    exec_steps = set()

    processed_steps = []
    unprocessed_steps = list(requested_steps)

    while unprocessed_steps:
      step = unprocessed_steps.pop()

      processed_steps.append(step)

      children = STEP_CASCADES.get(step, [])
      unprocessed_steps.extend(
          [c for c in children if c not in processed_steps])

      exec_steps.add(step)

    return sorted(list(exec_steps))

  @staticmethod
  def _retry_steps_to_strings(steps: List['RetryStep']) -> List['RetryStep']:
    """Return the string names of the given steps."""
    return [RetryStep.Name(step) for step in steps]

  def register(self):
    """Perform initial set up for checkpoint / mark the build as a retry."""
    if self._do_retry_summary:
      self.m.easy.set_properties_step(retry_summary={},
                                      step_name='update retry summary')

    if not self._retry_run:
      return
    with self.m.step.nest('RUNNING IN RETRY MODE') as presentation:
      if not self._original_build_bbid:
        raise StepFailure('no bbid specified')

      try:
        self._original_build = self.m.buildbucket.get(
            self._original_build_bbid, step_name='get original build')
      except:  #pylint: disable=bare-except
        pass
      if not self._original_build:
        raise StepFailure('could not fetch build %s' %
                          self._original_build_bbid)

      presentation.links['previous build'] = self.m.buildbucket.build_url(
          build_id=self._original_build_bbid)
      presentation.logs['retry plan'] = json.dumps(
          {
              'original_build_bbid': self._original_build_bbid,
              'run_steps': self._retry_steps_to_strings(self._run_steps),
              'builder_run_steps': {
                  k: self._retry_steps_to_strings(steps)
                  for k, steps in self._builder_run_steps.items()
              }
          }, indent=2)

      # Extract needed properties.
      with self.m.step.nest('verify previous build') as presentation:
        for recipe, trigger_step, inclusion, prop in ORIGINAL_BUILD_PROPERTIES:
          if self._original_build.input.properties['recipe'] == recipe:
            step_included = trigger_step is None or trigger_step in self._run_steps
            if trigger_step is None or inclusion == step_included:
              if prop not in self._original_build.output.properties:
                if prop == 'build_report_uri':
                  # Tolerate missing build report in case we're retrying a build that didn't get that far.
                  presentation.step_text = 'previous build had no build report, starting a new build report'
                else:
                  presentation.step_text = 'could not get `%s` from previous build' % prop
                  raise StepFailure(presentation.step_text)
              else:
                setattr(self, prop,
                        self._original_build.output.properties[prop])
                presentation.logs[prop] = getattr(self, prop)

        if self.child_builds is not None:
          self.child_builder_data = self.m.buildbucket.get_multi(
              [int(bbid) for bbid in self.child_builds],
              step_name='get child builder data')
          for bbid, build in self.child_builder_data.items():
            if build.input.properties['recipe'] == 'build_release':
              self._builder_children[bbid] = build

  def update_summary(self, step: 'RetryStep', status: str):
    """Update the retry_summary output property with the given step/status."""
    if not self._do_retry_summary:
      return
    if status not in [
        STATUS_STARTED, STATUS_SUCCESS, STATUS_SKIPPED, STATUS_FAILED
    ]:
      raise ValueError('unsupported status %s' % status)
    self._retry_summary[RetryStep.Name(step)] = status

    self.m.easy.set_properties_step(retry_summary=self._retry_summary,
                                    step_name='update retry summary')

  @contextmanager
  def retry(self, step: 'RetryStep'):
    """Context to handle retry logic / status reporting."""
    run_step = not self._retry_run or step in self._run_steps

    if run_step:
      try:
        self.update_summary(step, STATUS_STARTED)
        yield run_step
      except:
        self.update_summary(step, STATUS_FAILED)
        raise
      else:
        self.update_summary(step, STATUS_SUCCESS)
    else:
      # If we're not going to run the step,
      with self.m.step.nest('(RETRY-MODE) not retrying {}'.format(
          RetryStep.Name(step))):
        yield run_step
        self.update_summary(step, STATUS_SKIPPED)
