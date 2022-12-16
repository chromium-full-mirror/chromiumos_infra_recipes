# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
from contextlib import contextmanager
from typing import List

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.recipe_modules.chromeos.checkpoint.checkpoint import CheckpointProperties, RetryStep

STATUS_STARTED = "STARTED"
STATUS_SUCCESS = "SUCCESS"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAILED = "FAILED"

STEP_CASCADES = {
    # Orchestrator steps
    RetryStep.CREATE_BUILDSPEC: [RetryStep.RUN_CHILDREN],
    RetryStep.RUN_CHILDREN: [RetryStep.LAUNCH_TESTS],
    RetryStep.RUN_FAILED_CHILDREN: [RetryStep.LAUNCH_TESTS],

    # Child builder steps
    RetryStep.STAGE_ARTIFACTS: [RetryStep.PUSH_IMAGES],
    RetryStep.PUSH_IMAGES: [RetryStep.DEBUG_SYMBOLS, RetryStep.COLLECT_SIGNING],
    RetryStep.DEBUG_SYMBOLS: [RetryStep.COLLECT_SIGNING],
    RetryStep.COLLECT_SIGNING: [RetryStep.PAYGEN],

    # Paygen steps
    RetryStep.UPLOAD_PAYLOAD: [RetryStep.TEST_PAYLOAD],
}


ORIGINAL_BUILD_PROPERTIES = [
    # Of the form (recipe, trigger_step, property name)
    ('orchestrator', RetryStep.CREATE_BUILDSPEC, 'buildspec_gs_uri'),
    ('orchestrator', RetryStep.RUN_CHILDREN, 'child_builds'),
    ('build_release', RetryStep.STAGE_ARTIFACTS, 'artifact_link'),
    ('build_release', RetryStep.PUSH_IMAGES, 'signing_instructions_uris'),
]


class CheckpointApi(recipe_api.RecipeApi):
  """A module for managing release build checkpoints.

    See go/release-checkpoints-dd for context.
  """

  # TODO(b/262388770): Improve documentaton here, and link to a dev guide.

  def __init__(self, properties: CheckpointProperties, *args, **kwargs):
    super(CheckpointApi, self).__init__(*args, **kwargs)
    self._retry_run = properties.retry
    # If CREATE_BUILDSPEC is included we're just doing a full release build
    # so go ahead and turn off retry mode.
    if RetryStep.CREATE_BUILDSPEC in properties.exec_steps.steps:
      self._retry_run = False
      return

    self._original_build_bbid = properties.original_build_bbid
    if self._original_build_bbid:
      self._original_build_bbid = int(self._original_build_bbid)
    self._original_build = None

    self._retry_summary = {}

    # Do step cascades.
    self._run_steps = self.cascade(properties.exec_steps.steps)
    self._build_target_run_steps = {
        bt: self.cascade(steps.steps)
        for bt, steps in properties.build_target_exec_steps.items()
    }

    # Output properties from the previous builds.
    for _, _, prop in ORIGINAL_BUILD_PROPERTIES:
      setattr(self, prop, None)
    self.child_builder_data = None

  def is_run_step(self, step: "RetryStep"):
    """Return whether the step will be run in this retry."""
    return not self._retry_run or step in self._run_steps

  def builder_children(self) -> List[int]:
    """Gets the BBIDs of the child builders that are image builders."""
    child_builds = []
    for bbid, build in (self.child_builder_data or {}).items():
      if build.input.properties['recipe'] == 'build_release':
        child_builds.append(bbid)
    return child_builds

  def cascade(self, requested_steps: List["RetryStep"]):
    """Process step cascades for the requested steps.

      Returns: (List["RetryStep"]) all the steps that are meant to be run.
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

  def _retry_steps_to_strings(self, steps: List["RetryStep"]):
    return [RetryStep.Name(step) for step in steps]

  def register(self):
    """Perform initial set up for checkpoint / mark the build as a retry."""
    if not self._retry_run:
      return
    with self.m.step.nest("RUNNING IN RETRY MODE") as presentation:
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
              'build_target_run_steps': {
                  k: self._retry_steps_to_strings(steps)
                  for k, steps in self._build_target_run_steps.items()
              }
          }, indent=2)

      # Extract needed properties.
      with self.m.step.nest('verify previous build') as presentation:
        for recipe, trigger_step, prop in ORIGINAL_BUILD_PROPERTIES:
          if self._original_build.input.properties['recipe'] == recipe:
            if trigger_step not in self._run_steps:
              if prop not in self._original_build.output.properties:
                presentation.step_text = 'could not get `%s` from previous build' % prop
                raise StepFailure(presentation.step_text)
              setattr(self, prop, self._original_build.output.properties[prop])
              presentation.logs[prop] = getattr(self, prop)

        if self.child_builds is not None:
          self.child_builder_data = self.m.buildbucket.get_multi(
              [int(bbid) for bbid in self.child_builds],
              step_name='get child builder data')

  def update_summary(self, step: "RetryStep", status: str):
    """Updates the retry_summary output property with the given step/status."""
    # For now we don't want to alter non-retry builds.
    # TODO(b/262388770): Remove after additional testing.
    if not self._retry_run:
      return
    if status not in [
        STATUS_STARTED, STATUS_SUCCESS, STATUS_SKIPPED, STATUS_FAILED
    ]:
      raise ValueError('unsupported status %s' % status)
    self._retry_summary[RetryStep.Name(step)] = status

    self.m.easy.set_properties_step(retry_summary=self._retry_summary,
                                    step_name='update retry summary')

  @contextmanager
  def retry(self, step: "RetryStep"):
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
