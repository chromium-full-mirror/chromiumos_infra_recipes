# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'cros',
    'dev',
]


def RunSteps(api):
  assert api.cros.find_project_path('my/project', 'branch1') == 'src/project'
  api.cros.regen_portage_cache('my_overlay')
  api.cros.uprev_portage_packages()
  api.cros.push_portage_package_uprevs()
  api.dev.configure(dryrun=True)
  api.cros.uprev_portage_packages()
  api.cros.push_portage_package_uprevs()


def GenTests(api):
  yield api.test('basic')
