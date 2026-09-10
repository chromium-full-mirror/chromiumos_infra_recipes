# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the bump_version property function."""

from recipe_engine import post_process

DEPS = [
    'cros_version',
    'orch_menu',
    'recipe_engine/properties',
]


def RunSteps(api):
  # Access the property to ensure coverage
  _ = api.orch_menu.bump_version
  with api.orch_menu.setup_orchestrator():
    pass


def GenTests(api):
  yield api.test(
      'basic', api.cros_version.workspace_version('R100-15217.0.0'),
      api.properties(**{'$chromeos/orch_menu': {
          'bump_version': True
      }}))

  yield api.test(
      'uprev-fail', api.cros_version.workspace_version('R100-15217.0.0'),
      api.step_data(
          'set up orchestrator.uprev and push packages.push uprevs.push to src/overlay.git push src/overlay',
          retcode=1),
      api.post_check(post_process.SummaryMarkdown,
                     'Failed to uprev all changes'),
      api.post_process(post_process.DropExpectation),
      api.properties(**{'$chromeos/orch_menu': {
          'bump_version': True
      }}), status='FAILURE')
