# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the bump_version property function."""

DEPS = [
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
      'basic', api.properties(**{'$chromeos/orch_menu': {
          'bump_version': True
      }}))
