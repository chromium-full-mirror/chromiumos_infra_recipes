# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE SuiteManager builder."""

from PB.recipes.chromeos.test_platform.suite_scheduler import SuiteSchedulerProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
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

  with api.step.nest('Execute commands'):
    cmd = cipd_dir.join('suite_scheduler')
    with api.context(cwd=cipd_dir, infra_steps=True):
      api.step(
          'launch susch', [cmd, 'help', 'configs'],
          stdout=api.raw_io.output_text(name='stdout', add_output_log=True))


def GenTests(api):
  yield api.test('basic')
