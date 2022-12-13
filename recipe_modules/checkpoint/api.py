# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List

from recipe_engine import recipe_api

from PB.recipe_modules.chromeos.checkpoint.checkpoint import CheckpointProperties, RetryStep

STEP_CASCADES = {
    # Orchestrator steps
    RetryStep.CREATE_BUILDSPEC: [RetryStep.RUN_CHILDREN],
    RetryStep.RUN_CHILDREN: [RetryStep.LAUNCH_TESTS],
    RetryStep.RUN_FAILED_CHILDREN: [RetryStep.LAUNCH_TESTS],

    # Child builder steps
    # We currently can only run ebuild tests in the same build as building artifacts,
    # so if we build artifacts we better run the ebuild tests.
    RetryStep.STAGE_ARTIFACTS: [RetryStep.PUSH_IMAGES, RetryStep.EBUILD_TESTS],
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
    # Do step cascades.
    self._run_steps = self.cascade(properties.exec_steps.steps)
    self._build_target_run_steps = {
        bt: self.cascade(steps.steps)
        for bt, steps in properties.build_target_exec_steps.items()
    }

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
