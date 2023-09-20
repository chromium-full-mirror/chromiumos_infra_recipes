# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uploading test mappings to PVS requirements database."""

from PB.recipes.chromeos.pvs_run_script import PVSRunScriptProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/path',
    'recipe_engine/step',
]
PROPERTIES = PVSRunScriptProperties
PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api, properties):
  cipd_path = api.path['start_dir'].join('cipd')

  with api.step.nest('ensure reqdbtool'):
    pkgs = api.cipd.EnsureFile()
    pkgs.add_package(name='infra_internal/tools/pvs/reqdbtool/${platform}',
                     version='latest')
    api.cipd.ensure(cipd_path, pkgs)

  cmd = cipd_path.join('reqdbtool')
  api.step('run reqdbtool', [cmd, *properties.script_args])


def GenTests(api):
  yield api.test('basic')
