# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running PVS-related scripts.
"""

from PB.recipes.chromeos.pvs_run_script import PVSRunScriptProperties

DEPS = [
    'build_menu',
    'cros_sdk',
    'recipe_engine/context',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'workspace_util',
]
PROPERTIES = PVSRunScriptProperties
PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api, properties):
  with api.build_menu.configure_builder(
      missing_ok=True), api.build_menu.setup_workspace_and_chroot(
      ), api.context(cwd=api.workspace_util.workspace_path):
    api.cros_sdk.run(f'Call {properties.script_path}',
                     [properties.script_path] + list(properties.script_args),
                     stdout=api.raw_io.output_text(add_output_log=True))


def GenTests(api):
  yield api.test('basic')
