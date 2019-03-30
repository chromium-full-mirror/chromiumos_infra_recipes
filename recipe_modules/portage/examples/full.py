# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'dev',
    'portage',
]


def RunSteps(api):
  api.dev.configure(dryrun=True)
  api.portage.regen_cache('my_overlay')
  api.portage.uprev_packages()
  api.portage.push_package_uprevs()
  api.assertions.assertEqual(
      api.portage.portageq_best_visible_version('chromeos-chrome'),
      '74.0.3726.0')


def GenTests(api):
  yield api.test('basic')
