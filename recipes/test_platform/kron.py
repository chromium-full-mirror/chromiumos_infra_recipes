# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE Kron builder."""
import uuid

from PB.recipes.chromeos.test_platform.kron import KronProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_infra_config'
]
PROPERTIES = KronProperties


def RunSteps(api, properties):
  """Builder Entry Point

  Args:
    api: a RecipeScriptApi instance
    properties: default recipe properties

  Returns:
    None
  """

  cipd_dir = api.path.start_dir / 'cipd' / 'kron'

  with api.step.nest('Ensure kron'):
    with api.context(infra_steps=True):
      pkgs = api.cipd.EnsureFile()

      # Using the cipd label from properties allows us to have easier testing
      # of new features in LED tests
      pkgs.add_package('chromiumos/infra/kron/${platform}',
                       properties.cipd_label)
      api.cipd.ensure(cipd_dir, pkgs)

  with api.step.nest('Execute') as step_presentation:

    # Generate a RFC 4122 compliant random UUID
    run_uuid = str(uuid.uuid4())

    # Since uuids are unique, recipe expectations break when logging the id.
    if properties.is_recipe_test:
      run_uuid = 'test123'

    # Log UUID for kron run
    step_presentation.step_summary_text = 'run_id: %s' % (run_uuid)
    step_presentation.properties['kron-run'] = run_uuid

    cmd_path = cipd_dir / 'kron'
    subcommands = (
        ('launch NEW_BUILD tasks', '-new-builds'),
        ('launch TIMED_EVENT tasks', '-timed-events'),
        ('launch NEW_BUILD_3D tasks', '-new-builds-3d'),
        ('launch MULTI_DUT tasks', '-multidut'),
        ('launch NEW_BUILD_3D_BOARD_BASED tasks', '-new-builds-3d-board-based'),
    )
    failed_subcommands = []
    with api.context(cwd=cipd_dir, infra_steps=True):
      for step_name, flag in subcommands:
        command = [cmd_path, 'run', flag, '-run-id', run_uuid]

        if not api.cros_infra_config.is_staging:
          command.append('-prod')

        try:
          api.step(step_name, command)
        except api.step.StepFailure:
          failed_subcommands.append(step_name)
    if failed_subcommands:
      raise api.step.InfraFailure(
          f"kron subcommand(s) failed: {', '.join(failed_subcommands)}")


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(KronProperties(is_recipe_test=True)),
  )

  yield api.test(
      'subcommand_failure',
      api.properties(KronProperties(is_recipe_test=True)),
      api.step_data('Execute.launch MULTI_DUT tasks', retcode=1),
      api.post_process(
          post_process.StepException,
          'Execute.launch MULTI_DUT tasks',
      ),
      api.post_process(post_process.StepException, 'Execute'),
      api.post_process(
          post_process.MustRun,
          'Execute.launch NEW_BUILD_3D_BOARD_BASED tasks',
      ),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'subcommand_cancelled',
      api.properties(KronProperties(is_recipe_test=True)),
      api.step_data(
          'Execute.launch MULTI_DUT tasks',
          cancel=True,
          global_shutdown_event='after',
      ),
      api.post_process(
          post_process.StepCanceled,
          'Execute.launch MULTI_DUT tasks',
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Execute.launch NEW_BUILD_3D_BOARD_BASED tasks',
      ),
      api.post_process(post_process.DropExpectation),
      status='CANCELED',
  )
