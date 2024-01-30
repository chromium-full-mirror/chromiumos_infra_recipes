# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE SuiteManager builder."""
import uuid

from PB.recipes.chromeos.test_platform.suite_scheduler import SuiteSchedulerProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]
PROPERTIES = SuiteSchedulerProperties


def RunSteps(api, properties):
  """Builder Entry Point

  Args:
    api: a RecipeScriptApi instance
    properties: default recipe properties

  Returns:
    None
  """

  cipd_dir = api.path['start_dir'].join('cipd', 'suite_scheduler')

  with api.step.nest('Ensure Suite Scheduler V1.5'):
    with api.context(infra_steps=True):
      pkgs = api.cipd.EnsureFile()

      # Using the cipd label from properties allows us to have easier testing
      # of new features in LED tests
      pkgs.add_package('chromiumos/infra/suite_scheduler/${platform}',
                       properties.cipd_label)
      api.cipd.ensure(cipd_dir, pkgs)

  with api.step.nest('Execute') as step_presentation:

    # Generate a RFC 4122 compliant random UUID
    run_uuid = str(uuid.uuid4())

    # Since uuids are unique, recipe expectations break when logging the id.
    if properties.is_recipe_test:
      run_uuid = 'test123'

    # Log UUID for susch run
    step_presentation.step_summary_text = 'run_id: %s' % (run_uuid)
    step_presentation.properties['susch-run'] = run_uuid

    cmd = cipd_dir.join('suite_scheduler')
    with api.context(cwd=cipd_dir, infra_steps=True):
      #  TODO(b/317084435): pass in run_uuid as a cli argument
      api.step(
          'launch susch', [cmd, 'configs', '-new-build', '-name-only'],
          stdout=api.raw_io.output_text(name='stdout', add_output_log=True))


def GenTests(api):
  yield api.test('basic',
                 api.properties(SuiteSchedulerProperties(is_recipe_test=True)))
