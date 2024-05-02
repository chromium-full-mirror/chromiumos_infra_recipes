# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE Kron builder."""

from PB.recipes.chromeos.test_platform.kron_firestore import KronFirestoreProperties

DEPS = [
    'recipe_engine/cipd', 'recipe_engine/context', 'recipe_engine/path',
    'recipe_engine/properties', 'recipe_engine/raw_io', 'recipe_engine/step',
    'cros_infra_config'
]
PROPERTIES = KronFirestoreProperties


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

  with api.step.nest('Execute'):
    cmd_path = cipd_dir / 'kron'
    with api.context(cwd=cipd_dir, infra_steps=True):
      cmd = [cmd_path, 'firestore-sync']

      if not api.cros_infra_config.is_staging:
        cmd.append('-prod')

      api.step(
          'Sync ToT configs to Firestore', cmd,
          stdout=api.raw_io.output_text(name='stdout', add_output_log=True))


def GenTests(api):
  yield api.test('basic')
