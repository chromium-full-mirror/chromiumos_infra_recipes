# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE Kron builder."""
import uuid

from PB.recipes.chromeos.test_platform.kron import KronProperties

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
    with api.context(cwd=cipd_dir, infra_steps=True) as presentation:
      try:
        nb_command = [cmd_path, 'run', '-new-builds', '-run-id', run_uuid]

        if not api.cros_infra_config.is_staging:
          nb_command.append('-prod')

        api.step(
            'launch NEW_BUILD tasks', nb_command,
            stdout=api.raw_io.output_text(name='stdout', add_output_log=True))
      except Exception as e:  # pragma: no cover # pylint: disable=broad-except
        presentation.step_summary_text = "Unexpected error: '{}'".format(str(e))
        presentation.status = api.step.WARNING

    with api.context(cwd=cipd_dir, infra_steps=True) as presentation:
      try:
        te_command = [cmd_path, 'run', '-timed-events', '-run-id', run_uuid]

        if not api.cros_infra_config.is_staging:
          te_command.append('-prod')

        api.step(
            'launch TIMED_EVENT tasks', te_command,
            stdout=api.raw_io.output_text(name='stdout', add_output_log=True))
      except Exception as e:  # pragma: no cover # pylint: disable=broad-except
        presentation.step_summary_text = "Unexpected error: '{}'".format(str(e))
        presentation.status = api.step.WARNING

    with api.context(cwd=cipd_dir, infra_steps=True) as presentation:
      try:
        nb_3d_command = [cmd_path, 'run', '-new-builds-3d', '-run-id', run_uuid]

        if not api.cros_infra_config.is_staging:
          nb_3d_command.append('-prod')

        api.step(
            'launch NEW_BUILD_3D tasks', nb_3d_command,
            stdout=api.raw_io.output_text(name='stdout', add_output_log=True))
      except Exception as e:  # pragma: no cover # pylint: disable=broad-except
        presentation.step_summary_text = "Unexpected error: '{}'".format(str(e))
        presentation.status = api.step.WARNING



def GenTests(api):
  yield api.test('basic',
                 api.properties(KronProperties(is_recipe_test=True)))
