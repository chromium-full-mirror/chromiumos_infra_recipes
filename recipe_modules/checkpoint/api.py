# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List
from contextlib import contextmanager

from recipe_engine import recipe_api

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
    RetryStep.PUSH_IMAGES: [RetryStep.DEBUG_SYMBOLS],
    RetryStep.DEBUG_SYMBOLS: [RetryStep.PAYGEN],

    # Paygen steps
    RetryStep.UPLOAD_PAYLOAD: [RetryStep.TEST_PAYLOAD],
}


class CrosCheckpointApi(recipe_api.RecipeApi):
  """A module for managing release build checkpoints.

    See go/release-checkpoints-dd for context.
  """

  # TODO(b/262388770): Improve documentaton here, and link to a dev guide.

  def __init__(self, properties: CheckpointProperties, *args, **kwargs):
    super(CrosCheckpointApi, self).__init__(*args, **kwargs)
    self._retry_run = properties.retry
    # Do step cascades.
    self._run_steps = self.cascade(properties.exec_steps.steps)
    self._build_target_run_steps = {
        bt: self.cascade(steps.steps)
        for bt, steps in properties.build_target_exec_steps.items()
    }
    self._retry_summary = {}

  def will_run_step(self, step: "RetryStep"):
    """Return whether the step will be run in this retry."""
    return not self._retry_run or step in self._run_steps

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

    try:
      if not run_step:
        # If we're not going to run the step,
        with self.m.step.nest('(RETRY-MODE) not retrying {}'.format(
            RetryStep.Name(step))):
          yield run_step
      else:
        yield run_step
    except:
      self.update_summary(step, STATUS_FAILED)
      raise
    else:
      self.update_summary(step, STATUS_SUCCESS if run_step else STATUS_SKIPPED)
