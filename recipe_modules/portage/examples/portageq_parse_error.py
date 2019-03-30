# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'portage',
]


def RunSteps(api):
  api.assertions.assertRaises(
      ValueError, api.portage.portageq_best_visible_version, 'chromeos-chrome')


def GenTests(api):
  yield api.test('portageq parse error') + api.step_data(
      'portageq best_visible chromeos-chrome',
      stdout=api.raw_io.output('a_malformed_package_string5'))
