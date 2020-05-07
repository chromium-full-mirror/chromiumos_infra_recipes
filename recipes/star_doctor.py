# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

DEPS = [
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
    with api.depot_tools.on_path():
      api.step('regenerate configs', ['/bin/bash', regen_path, '-b'],
               timeout=3 * 60)


def GenTests(api):
  yield api.test('basic')
