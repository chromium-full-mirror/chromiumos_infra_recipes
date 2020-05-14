# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'git',
]

INFRA_CONFIG_URL = 'https://chrome-internal.googlesource.com/chromeos/infra/config'


def RunSteps(api):
  with api.step.nest('set up'):
    workdir = api.path.mkdtemp()
    api.git.clone(INFRA_CONFIG_URL, target_path=workdir, timeout_sec=3 * 60)
    regen_path = workdir.join('regenerate_configs.sh')

  with api.step.nest('generate binary config'):
    # We need lucicfg from depot_tools.
    with api.depot_tools.on_path():
      # We need protoc from cipd.
      cipd_dir = api.path.mkdtemp()
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/tools/protoc/linux-amd64',
                       'protobuf_version:v3.11.4')
      api.cipd.ensure(cipd_dir, pkgs)
      with api.context(**{'env_suffixes': {'PATH': [cipd_dir]}}):
        api.step('regenerate configs', ['/bin/bash', regen_path, '-b'],
                 timeout=3 * 60)


def GenTests(api):
  yield api.test('basic')
